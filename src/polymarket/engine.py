"""Ties client/strategy/risk/gateway/state together into one cycle —
analogous to src/orchestrator.py's run_trading_cycle(), run repeatedly
by scripts/run_polymarket_bot.py's loop rather than per-cycle by an
external scheduler, since nothing here needs an agent to relay data
(client.py calls the real API directly)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.polymarket import reconciliation
from src.polymarket.btc_entry_signal import assess_btc_entry_direction, build_entry_candidate
from src.polymarket.btc_market_data import BtcPriceHistoryStore
from src.polymarket.client import NoActiveMarketError, PolymarketClient
from src.polymarket.entry_guard import check_entry_retry_guard
from src.polymarket.exit_manager import check_and_execute_dynamic_exits
from src.polymarket.gateway import ExecutionGateway
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import BinaryMarket, OrderRequest
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import PolymarketPositionStore
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
    reconciled_count: int = 0
    exits_submitted: int = 0


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
        cost = position.filled_size_usd  # actual cost paid, from the verified fill — not the requested size
        pnl = (position.filled_shares - cost) if won else -cost
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
    strategy: BtcMomentumStrategy,  # kept for call-site/signature compatibility -- no longer consulted for the live entry decision, see below
    risk_manager: PolymarketRiskManager,
    gateway: ExecutionGateway,
    decision_logger: PolymarketDecisionLogger,
    state_store: DailyPnlStateStore,
    position_store: PolymarketPositionStore,
    pending_store: PolymarketPendingOrderStore,
    history: MarketHistory,
    btc_price_store: BtcPriceHistoryStore,
    btc_feed_source: str = "manual",
    now: datetime | None = None,
) -> CycleReport:
    now = now or datetime.now(timezone.utc)

    # Task 5: sweep for any order placed in a PRIOR cycle (or a prior
    # process, if the bot restarted) that reached the exchange but was
    # never reconciled — e.g. confirm_and_place() was called from a
    # separate approval step after run_cycle() already returned. Always
    # runs first, before this cycle proposes anything new, so the
    # position/state ledger a new trade's risk checks read from (open
    # position count, daily P&L) reflects reality.
    #
    # A DELAYED entry (one that sat UNKNOWN across earlier cycles) can
    # resolve FILLED right here, creating a position THIS call -- a
    # live incident showed that position then getting immediately
    # exited by the dynamic-exit pass a few lines below, in the SAME
    # cycle, on fresh evidence that had nothing to do with the stale
    # thesis the entry was originally made under. An ordinary brand-new
    # entry never has this problem (it's created further down in this
    # same function, AFTER the dynamic-exit pass already ran) -- so the
    # fix is just giving a delayed adoption the same one-cycle grace an
    # ordinary entry already gets for free: snapshot which
    # client_order_ids exist before this sweep, diff against after, and
    # tell check_and_execute_dynamic_exits() to defer evaluating exactly
    # those (see exit_manager.py's module docstring, DELAYED-ENTRY GRACE).
    client_order_ids_before_reconcile = {p.client_order_id for p in position_store.load()}
    reconciled = reconciliation.reconcile_pending_orders(
        client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger, now=now,
    )
    newly_adopted_client_order_ids = frozenset(
        p.client_order_id for p in position_store.load() if p.client_order_id not in client_order_ids_before_reconcile
    )

    settled = settle_resolved_positions(
        client=client, position_store=position_store, state_store=state_store, decision_logger=decision_logger, now=now,
    )

    # Evidence-gated dynamic exit check (see exit_manager.py):
    # deliberately placed AFTER settlement (a position that already
    # resolved this cycle is gone, nothing to exit-check) and BEFORE any
    # new-entry evaluation below, so the open-position count a new
    # trade's risk checks read reflects any exit that just closed. A
    # complete no-op while settings.dynamic_exit_enabled is False (the
    # default). Never touches MAX_BET_SIZE/MAX_DAILY_LOSS/MAX_SPREAD/
    # ORDER_BOOK_LIQUIDITY/ENTRY_CUTOFF or anything below this point.
    exits_submitted = check_and_execute_dynamic_exits(
        client=client, settings=settings, gateway=gateway, position_store=position_store,
        pending_store=pending_store, state_store=state_store, decision_logger=decision_logger,
        btc_price_store=btc_price_store, history=history, btc_feed_source=btc_feed_source,
        skip_client_order_ids=newly_adopted_client_order_ids, now=now,
    )

    try:
        market = client.find_active_btc_market(now=now)
    except NoActiveMarketError as exc:
        decision_logger.log_decision(kind="no_trade", reason=str(exc))
        return CycleReport(
            ran=True, skipped_reason=str(exc), settled_count=settled, reconciled_count=reconciled,
            exits_submitted=exits_submitted,
        )

    # history.observe() still runs every cycle -- its own result just no
    # longer decides entry direction (see below). It remains the ONLY
    # source of `history.mids`, which exit_manager.py's dynamic-exit
    # pass reads next cycle for Polymarket's own order-book-momentum
    # microstructure signal (corroboration/veto there, never a trigger
    # here either) -- removing this call would silently starve that
    # unrelated, still-active exit-side signal.
    history.observe(market)

    # --- COINBASE BTC -> directional entry thesis (see btc_entry_signal.py) --
    # Polymarket price/order-book data plays NO part in this decision --
    # a YES mid moving up or down, by itself, can never create or block
    # an entry; only real Coinbase BTC evidence can. Reuses the EXACT
    # SAME scoring pipeline exit_manager.py's dynamic-exit decision
    # already relies on (build_btc_momentum_evidence/evaluate_momentum/
    # compute_feed_status) -- never a second, competing BTC engine.
    try:
        bars = btc_price_store.get_bars(interval_seconds=settings.btc_bar_interval_seconds, now=now)
    except Exception as exc:  # noqa: BLE001 - a BTC store failure must never crash the bot or fall back to the old Polymarket-only trigger
        decision_logger.log_decision(
            kind="btc_feed_read_failed",
            reason=f"Could not read BTC price history for entry evaluation on {market.condition_id}: {exc}",
            evidence={"condition_id": market.condition_id, "error_type": type(exc).__name__, "error": str(exc)},
        )
        bars = []

    btc_direction = assess_btc_entry_direction(
        bars, now=now, max_bar_age_seconds=settings.btc_max_bar_age_seconds, feed_source=btc_feed_source,
        min_strengthening_signals=settings.min_strengthening_signals_for_entry,
    )
    feed_status = btc_direction.feed_status
    # Logged every cycle, for every active market, regardless of what
    # else happens -- mirrors check_and_execute_dynamic_exits' own
    # always-on btc_feed_status logging, so a dead/thin feed or a
    # conflicting read is visible in the decision log, never silent.
    decision_logger.log_decision(
        kind="btc_entry_signal",
        reason=(
            f"BTC_DIRECTION={btc_direction.direction} BTC_EDGE_POINTS={btc_direction.edge_points:+.0f} "
            f"BTC_STATE={btc_direction.momentum_state.value if btc_direction.momentum_state else 'n/a'} "
            f"BTC_FEED_STATUS={feed_status.status} {btc_direction.reason}"
        ),
        evidence={
            "market_slug": market.condition_id, "condition_id": market.condition_id,
            "btc_direction": btc_direction.direction,
            "btc_edge_points": btc_direction.edge_points,
            "btc_momentum_state": btc_direction.momentum_state.value if btc_direction.momentum_state else None,
            "fired_signals": list(btc_direction.selected_assessment.btc_assessment.signals) if btc_direction.selected_assessment else [],
            "bullish_edge_points": btc_direction.bullish_edge_points, "bearish_edge_points": btc_direction.bearish_edge_points,
            "bullish_state": btc_direction.bullish_assessment.state.value, "bearish_state": btc_direction.bearish_assessment.state.value,
            "btc_feed_source": feed_status.source,
            "btc_last_bar_time": feed_status.last_bar_time.isoformat() if feed_status.last_bar_time else None,
            "btc_bar_age_seconds": feed_status.bar_age_seconds, "btc_feed_status": feed_status.status,
            "remaining_seconds": market.seconds_to_close,
        },
    )

    if btc_direction.direction == "neutral":
        decision_logger.log_decision(
            kind="no_trade", reason=btc_direction.reason,
            evidence={
                "question": market.question, "rejection_reason": btc_direction.neutral_reason_code,
                "remaining_seconds": market.seconds_to_close,
            },
        )
        return CycleReport(
            ran=True, market_question=market.question, settled_count=settled, reconciled_count=reconciled,
            exits_submitted=exits_submitted,
        )

    # --- POLYMARKET -> execution confirmation (direction already decided above) --
    # Maps bullish->YES / bearish->NO against the CURRENT market's own
    # two-sided quote -- never a price guess, never the other side.
    candidate = build_entry_candidate(market, btc_direction, size_usd=settings.max_bet_usd)
    if candidate is None:
        decision_logger.log_decision(
            kind="no_trade",
            reason=(
                f"Coinbase BTC evidence is {btc_direction.direction} but {btc_direction.outcome} has no "
                f"two-sided Polymarket quote yet on {market.condition_id}"
            ),
            evidence={
                "question": market.question, "rejection_reason": "unusable_outcome_quote",
                "btc_direction": btc_direction.direction, "selected_outcome": btc_direction.outcome,
            },
        )
        return CycleReport(
            ran=True, market_question=market.question, settled_count=settled, reconciled_count=reconciled,
            exits_submitted=exits_submitted,
        )

    token_id = market.token_id_for(candidate.thesis.outcome)
    # The outcome's OWN order book — never inferred from the other side,
    # never approximated from BinaryMarket.yes_bid/yes_ask (see
    # models.OrderBookSnapshot's and BinaryMarket's docstrings). This is
    # the only book the liquidity check and the order's max_price may be
    # computed from.
    #
    # A real incident: an uncaught polymarket_us.errors.RateLimitError
    # (Cloudflare 1015 on gateway.polymarket.us) out of this exact call
    # crashed the whole bot process. us_client.get_order_book() already
    # retries a rate limit internally with bounded backoff (see
    # us_client._retry_on_rate_limit) before ever raising, so reaching
    # this except at all means retries were exhausted (or some other,
    # non-rate-limit failure happened) — either way, a safe no-trade
    # skip for THIS cycle, never a crash and never a fabricated order
    # book. No order is placed down either path.
    try:
        order_book = client.get_order_book(token_id)
    except Exception as exc:  # noqa: BLE001 - a book-fetch failure (rate limit or otherwise) must never crash the bot or be treated as tradeable
        decision_logger.log_decision(
            kind="no_trade",
            reason=(
                f"Could not fetch {candidate.thesis.outcome}'s order book on {market.condition_id} "
                f"after retries: {type(exc).__name__}: {exc} -- sitting this cycle out"
            ),
            evidence={"token_id": token_id, "error_type": type(exc).__name__, "error": str(exc)},
        )
        return CycleReport(
            ran=True, market_question=market.question, settled_count=settled, reconciled_count=reconciled,
            exits_submitted=exits_submitted,
        )
    if order_book.best_ask is None:
        decision_logger.log_decision(
            kind="no_trade",
            reason=f"No ask-side liquidity in {candidate.thesis.outcome}'s order book on {market.condition_id}",
            evidence={"token_id": token_id},
        )
        return CycleReport(
            ran=True, market_question=market.question, settled_count=settled, reconciled_count=reconciled,
            exits_submitted=exits_submitted,
        )

    # Hard ceiling the exchange will not cross, anchored to the REAL best
    # ask (not the strategy's own suggested_entry_price, which for NO is
    # only a `1 - yes_bid` estimate) plus a small configured slippage
    # allowance. Clamped below 1.0 — OrderRequest requires max_price < 1.0.
    max_price = round(min(order_book.best_ask * (1 + settings.max_price_slippage_pct), 0.99), 4)

    state = state_store.load(today=now.date())
    decision = risk_manager.evaluate_new_trade(
        size_usd=candidate.suggested_size_usd, market=market, state=state,
        order_book=order_book, side="BUY", max_price=max_price, now=now,
    )
    if not decision.allowed:
        decision_logger.log_risk_block(decision, context="new_trade")
        return CycleReport(
            ran=True, market_question=market.question, settled_count=settled, reconciled_count=reconciled,
            exits_submitted=exits_submitted,
        )

    # Idempotency/retry guard (see entry_guard.py) — deliberately
    # separate from the risk checks above: a live incident showed
    # auto-execute repeatedly resubmitting a live BUY for the exact
    # same market/outcome every cycle after an unknown/rejected result
    # (open_position_count never moved, so MAX_OPEN_POSITIONS never
    # caught it). This never touches reconciliation's own unknown-fill
    # handling — it only decides whether a NEW submission may happen
    # yet for this exact (condition_id, outcome).
    retry_decision = check_entry_retry_guard(
        pending_store, position_store, condition_id=market.condition_id, outcome=candidate.thesis.outcome,
        candidate_max_price=max_price, cooldown_seconds=settings.entry_retry_cooldown_seconds,
        min_price_change=settings.entry_retry_min_price_change, now=now,
    )
    if retry_decision.blocked:
        decision_logger.log_decision(
            kind="entry_retry_blocked", reason=retry_decision.reason,
            evidence={
                "condition_id": market.condition_id, "outcome": candidate.thesis.outcome,
                "candidate_max_price": max_price, "blocking_pending_order_id": retry_decision.blocking_pending_order_id,
            },
        )
        return CycleReport(
            ran=True, market_question=market.question, settled_count=settled, reconciled_count=reconciled,
            exits_submitted=exits_submitted,
        )

    order = OrderRequest(
        condition_id=market.condition_id, token_id=token_id, outcome=candidate.thesis.outcome, side="BUY",
        size_usd=candidate.suggested_size_usd, max_price=max_price, close_time=market.close_time,
        reason=candidate.thesis.catalyst, order_type=settings.default_order_type,
    )
    result = gateway.submit_order(order)

    entered = False
    if result.status == "simulated_fill":
        # Paper mode: gateway.py already built the synthetic FillResult
        # directly (nothing to reconcile for a simulation — see
        # gateway.py's docstring), but it must still become a position
        # through the exact same idempotent path reconciliation.py uses
        # for real fills, never a second, parallel way to create one.
        assert result.fill_result is not None
        position = reconciliation.record_fill(
            result.fill_result, order, result.fill_result.order_id,
            position_store=position_store, state_store=state_store, decision_logger=decision_logger, now=now,
        )
        entered = position is not None
    elif result.status == "submitted":
        # live_auto_execute=True: the order already reached the exchange
        # this cycle. Reconcile it immediately rather than waiting for
        # the next cycle's sweep, so this cycle's own report reflects
        # what actually happened, not just what was submitted.
        pending_order_id = result.extra.get("pending_order_id") if result.extra else None
        pending = pending_store.get(pending_order_id) if pending_order_id else None
        if pending is not None:
            fill = reconciliation.reconcile_order(
                pending, client=client, pending_store=pending_store, position_store=position_store,
                state_store=state_store, decision_logger=decision_logger, now=now,
            )
            entered = bool(fill and fill.is_fill)
            reconciled += 1
    # result.status == "awaiting_approval": nothing to reconcile yet — a
    # separate confirm_and_place() call (or a later
    # reconcile_pending_orders() sweep, including after a restart) picks
    # this up once a human approves it and it actually reaches the
    # exchange. result.status == "rejected"/"failed": gateway.py already
    # marked the pending order fill_reconciled=True (nothing to
    # reconcile — the exchange never accepted it, or it never reached
    # the exchange at all).

    return CycleReport(
        ran=True, market_question=market.question, entered=entered,
        settled_count=settled, reconciled_count=reconciled, exits_submitted=exits_submitted,
    )
