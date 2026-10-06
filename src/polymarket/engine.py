"""Ties client/strategy/risk/gateway/state together into one cycle —
analogous to src/orchestrator.py's run_trading_cycle(), run repeatedly
by scripts/run_polymarket_bot.py's loop rather than per-cycle by an
external scheduler, since nothing here needs an agent to relay data
(client.py calls the real API directly)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.polymarket.client import NoActiveMarketError, PolymarketClient
from src.polymarket.gateway import ExecutionGateway, LivePolymarketGateway
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import BinaryMarket, OrderRequest
from src.polymarket.positions import OpenPosition, PolymarketPositionStore
from src.polymarket.risk import PolymarketRiskManager
from src.polymarket.settings import PolymarketSettings
from src.polymarket.state import DailyPnlStateStore
from src.polymarket.strategy import BtcMomentumStrategy


@dataclass
class CycleReport:
    ran: bool
    skipped_reason: str | None = None
    market_question: str | None = None
    entered: bool = False
    settled_count: int = 0


@dataclass
class MarketHistory:
    """In-memory only, by design: a restart losing a few minutes of this
    particular market's own price history is an acceptable cost (the
    strategy just waits for min_samples again), far cheaper than adding
    another file-backed store for data that's only ever useful within
    one 15-minute window."""

    condition_id: str | None = None
    mids: list[float] = field(default_factory=list)

    def observe(self, market: BinaryMarket) -> list[float]:
        if market.condition_id != self.condition_id:
            self.condition_id = market.condition_id
            self.mids = []
        if market.yes_mid is not None:
            self.mids.append(market.yes_mid)
        return list(self.mids)


def settle_resolved_positions(
    *, client: PolymarketClient, position_store: PolymarketPositionStore,
    state_store: DailyPnlStateStore, decision_logger: PolymarketDecisionLogger, now: datetime | None = None,
) -> int:
    now = now or datetime.now(timezone.utc)
    settled = 0
    for position in position_store.load():
        close_time = position.close_time if position.close_time.tzinfo else position.close_time.replace(tzinfo=timezone.utc)
        if now < close_time:
            continue
        winner = client.get_resolution(position.condition_id)
        if winner is None:
            continue  # resolved-by-clock but not yet reflected by the API; try again next cycle

        won = winner == position.outcome
        pnl = (position.shares - position.size_usd) if won else -position.size_usd
        decision_logger.log_decision(
            kind="position_settled",
            reason=f"{position.outcome} on {position.condition_id} {'WON' if won else 'LOST'}: pnl=${pnl:.2f}",
            evidence={"position": position.to_dict(), "winner": winner, "pnl_usd": pnl},
        )
        state = state_store.load(today=now.date())
        state.realized_pnl_usd += pnl
        state.open_position_count = max(0, state.open_position_count - 1)
        state.last_exit_time = now.isoformat()
        state_store.save(state)
        position_store.remove(position.condition_id)
        settled += 1
    return settled


def run_cycle(
    *,
    settings: PolymarketSettings,
    client: PolymarketClient,
    strategy: BtcMomentumStrategy,
    risk_manager: PolymarketRiskManager,
    gateway: ExecutionGateway,
    decision_logger: PolymarketDecisionLogger,
    state_store: DailyPnlStateStore,
    position_store: PolymarketPositionStore,
    history: MarketHistory,
    now: datetime | None = None,
) -> CycleReport:
    now = now or datetime.now(timezone.utc)

    settled = settle_resolved_positions(
        client=client, position_store=position_store, state_store=state_store, decision_logger=decision_logger, now=now,
    )

    try:
        market = client.find_active_btc_market(now=now)
    except NoActiveMarketError as exc:
        decision_logger.log_decision(kind="no_trade", reason=str(exc))
        return CycleReport(ran=True, skipped_reason=str(exc), settled_count=settled)

    recent_mids = history.observe(market)

    candidate = strategy.evaluate(market, recent_mids)
    if candidate is None:
        decision_logger.log_decision(
            kind="no_trade", reason="No qualifying setup this cycle",
            evidence={"question": market.question, "yes_mid": market.yes_mid, "samples": len(recent_mids)},
        )
        return CycleReport(ran=True, market_question=market.question, settled_count=settled)

    state = state_store.load(today=now.date())
    decision = risk_manager.evaluate_new_trade(size_usd=candidate.suggested_size_usd, market=market, state=state, now=now)
    if not decision.allowed:
        decision_logger.log_risk_block(decision, context="new_trade")
        return CycleReport(ran=True, market_question=market.question, settled_count=settled)

    order = OrderRequest(
        token_id=market.token_id_for(candidate.thesis.outcome), outcome=candidate.thesis.outcome, side="BUY",
        price=candidate.suggested_entry_price, size_usd=candidate.suggested_size_usd, reason=candidate.thesis.catalyst,
    )
    result = gateway.submit_order(order)

    if result.status in {"simulated_fill", "placed"}:
        shares = candidate.suggested_size_usd / candidate.suggested_entry_price
        position_store.add(OpenPosition(
            condition_id=market.condition_id, token_id=order.token_id, outcome=candidate.thesis.outcome,
            entry_price=candidate.suggested_entry_price, size_usd=candidate.suggested_size_usd, shares=shares,
            opened_at=now, close_time=market.close_time,
        ))
        state.trades_opened += 1
        state.open_position_count += 1
        state_store.save(state)
    elif result.status == "awaiting_approval" and isinstance(gateway, LivePolymarketGateway):
        # Pending approval doesn't open a position yet — confirm_and_place()
        # (called separately, per gateway.py's design) does, once approved.
        # live_auto_execute=True skips this branch since result.status would
        # already be "placed" by the time submit_order() returns.
        pass

    return CycleReport(ran=True, market_question=market.question, entered=result.status in {"simulated_fill", "placed"}, settled_count=settled)
