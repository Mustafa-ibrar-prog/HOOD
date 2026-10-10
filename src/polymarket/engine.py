"""Ties client/strategy/risk/gateway/state together into one cycle —
analogous to src/orchestrator.py's run_trading_cycle(), run repeatedly
by scripts/run_polymarket_bot.py's loop rather than per-cycle by an
external scheduler, since nothing here needs an agent to relay data
(client.py calls the real API directly).

PRODUCTION STRATEGY (as of this round): a deliberately simple,
Polymarket-price-only strategy -- see simple_entry_signal.py (entry)
and take_profit.py (exit, a fixed +5% target, no stop-loss). Entry is
evaluated continuously across the FULL 15-minute market -- there is
no "only in the final N minutes" restriction any more. Coinbase BTC
intelligence (btc_entry_signal.py), the settlement-reference
divergence check (reference_divergence.py), confidence scoring
(entry_confidence.py), and historical self-learning (trade_learning.py's
adjustment machinery) are NOT CALLED from run_cycle() at all -- they
remain in the codebase, with their own tests, in case they're wanted
again later, but none of them influences a live entry or exit
decision any more. trade_learning.CompletedTradeStore is still used,
but only for its RECORD-KEEPING role (record_completed_trade at
settlement/exit) -- never for its historical-adjustment role, which
this module never calls.

check_and_execute_dynamic_exits() (exit_manager.py, BTC-evidence-
based) and trailing_stop.check_and_execute_trailing_stops() (the
earlier +20% trailing-stop exit) are likewise no longer called --
take_profit.check_and_execute_take_profits() is the only exit logic
that runs, so a position opened by this strategy is never
independently sold by either earlier exit system too. There is no
stop-loss: a losing position is held until either the +5% target is
reached or the market resolves."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.polymarket import reconciliation
from src.polymarket.btc_market_data import BtcPriceHistoryStore
from src.polymarket.client import NoActiveMarketError, PolymarketClient
from src.polymarket.entry_guard import check_entry_retry_guard
from src.polymarket.gateway import ExecutionGateway
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import BinaryMarket, OrderRequest
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import PolymarketPositionStore
from src.polymarket.risk import PolymarketRiskManager
from src.polymarket.settings import PolymarketSettings
from src.polymarket.simple_entry_signal import assess_simple_entry
from src.polymarket.state import DailyPnlStateStore
from src.polymarket.strategy import BtcMomentumStrategy
from src.polymarket.take_profit import check_and_execute_take_profits
from src.polymarket.trade_learning import CompletedTradeStore, STRATEGY_ID_SIMPLE_PRICE_THRESHOLD, record_completed_trade


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
    trade_store: CompletedTradeStore | None = None,
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
        # Resolution pays exactly $1/share if won, $0 if lost -- a real,
        # known exit price, never a guess (see TASK 2's "never fabricate").
        record_completed_trade(
            trade_store, position, exit_timestamp=now, exit_price=(1.0 if won else 0.0),
            exit_reason="SETTLEMENT", fees_usd=0.0, realized_pnl_usd=pnl,
        )
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
    trade_store: CompletedTradeStore | None = None,
    reference_price_store: BtcPriceHistoryStore | None = None,
    reference_feed_source: str = "manual",
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
        trade_store=trade_store,
    )

    # Fixed +5% take-profit exit check (see take_profit.py) -- the
    # ONLY production exit logic as of this round. Deliberately placed
    # AFTER settlement (a position that already resolved this cycle is
    # gone, nothing to exit-check) and BEFORE any new-entry evaluation
    # below, so the open-position count a new trade's risk checks read
    # reflects any exit that just closed. Never touches MAX_BET_SIZE/
    # MAX_DAILY_LOSS/MAX_SPREAD/ORDER_BOOK_LIQUIDITY/ENTRY_CUTOFF or
    # anything below this point.
    exits_submitted = check_and_execute_take_profits(
        client=client, settings=settings, gateway=gateway, position_store=position_store,
        pending_store=pending_store, state_store=state_store, decision_logger=decision_logger,
        trade_store=trade_store, skip_client_order_ids=newly_adopted_client_order_ids, now=now,
    )

    try:
        market = client.find_active_btc_market(now=now)
    except NoActiveMarketError as exc:
        decision_logger.log_decision(kind="no_trade", reason=str(exc))
        return CycleReport(
            ran=True, skipped_reason=str(exc), settled_count=settled, reconciled_count=reconciled,
            exits_submitted=exits_submitted,
        )

    # history.observe() still runs every cycle -- harmless bookkeeping,
    # kept for whatever future use (nothing in the production path
    # reads history.mids any more -- see module docstring).
    history.observe(market)

    # The now-aware computation, NEVER BinaryMarket.seconds_to_close
    # (which reads real wall-clock time and would make this
    # non-deterministic under a test's fixed `now`) -- kept purely for
    # logging/record-keeping (trade_learning.py's seconds_remaining_at_entry
    # bucketing). There is no "too early to evaluate" gate any more:
    # the simple entry signal is evaluated every cycle across the FULL
    # 15-minute market, not only its final minutes.
    close_time = market.close_time if market.close_time.tzinfo else market.close_time.replace(tzinfo=timezone.utc)
    seconds_remaining = (close_time - now).total_seconds()

    # --- CHECK REAL YES/NO ASK (see simple_entry_signal.py) -- BOTH
    # outcomes' own order books are needed up front: which side (if
    # either) qualifies isn't known until both are checked. Same
    # rate-limit-safe, never-crash handling as before.
    try:
        yes_order_book = client.get_order_book(market.token_id_yes)
        no_order_book = client.get_order_book(market.token_id_no)
    except Exception as exc:  # noqa: BLE001 - a book-fetch failure (rate limit or otherwise) must never crash the bot or be treated as tradeable
        decision_logger.log_decision(
            kind="no_trade",
            reason=(
                f"Could not fetch YES/NO order books on {market.condition_id} after retries: "
                f"{type(exc).__name__}: {exc} -- sitting this cycle out"
            ),
            evidence={"condition_id": market.condition_id, "error_type": type(exc).__name__, "error": str(exc)},
        )
        return CycleReport(
            ran=True, market_question=market.question, settled_count=settled, reconciled_count=reconciled,
            exits_submitted=exits_submitted,
        )

    signal = assess_simple_entry(
        yes_order_book=yes_order_book, no_order_book=no_order_book, ask_threshold=settings.simple_entry_ask_threshold,
    )
    decision_logger.log_decision(
        kind="simple_entry_signal",
        reason=(
            f"YES_ASK={signal.yes_ask} NO_ASK={signal.no_ask} OUTCOME={signal.outcome} "
            f"REMAINING_SECONDS={seconds_remaining:.0f} {signal.reason}"
        ),
        evidence={
            "condition_id": market.condition_id, "yes_ask": signal.yes_ask, "no_ask": signal.no_ask,
            "outcome": signal.outcome, "remaining_seconds": seconds_remaining,
        },
    )
    if signal.outcome is None:
        decision_logger.log_decision(
            kind="no_trade", reason=signal.reason,
            evidence={
                "question": market.question, "rejection_reason": "no_qualifying_ask",
                "remaining_seconds": seconds_remaining, "yes_ask": signal.yes_ask, "no_ask": signal.no_ask,
            },
        )
        return CycleReport(
            ran=True, market_question=market.question, settled_count=settled, reconciled_count=reconciled,
            exits_submitted=exits_submitted,
        )

    outcome = signal.outcome
    token_id = market.token_id_for(outcome)
    # The SAME order book already fetched above for this outcome --
    # never re-fetched, never inferred from the other side. best_ask is
    # guaranteed not-None here: assess_simple_entry only ever returns a
    # non-None outcome when that side's own best_ask cleared the
    # threshold, which is itself only possible when best_ask exists.
    order_book = yes_order_book if outcome == "YES" else no_order_book

    # Hard ceiling the exchange will not cross, anchored to the REAL
    # best ask plus a small configured slippage allowance. Clamped
    # below 1.0 — OrderRequest requires max_price < 1.0. Keeps the
    # existing aggressive LIMIT + FOK execution model — never an
    # unrestricted market order.
    max_price = round(min(order_book.best_ask * (1 + settings.max_price_slippage_pct), 0.99), 4)
    size_usd = settings.simple_entry_size_usd  # fixed $20 (minimum == maximum), validated at load time

    state = state_store.load(today=now.date())
    decision = risk_manager.evaluate_new_trade(
        size_usd=size_usd, market=market, state=state, order_book=order_book, side="BUY", max_price=max_price, now=now,
    )
    if not decision.allowed:
        decision_logger.log_risk_block(decision, context="new_trade")
        return CycleReport(
            ran=True, market_question=market.question, settled_count=settled, reconciled_count=reconciled,
            exits_submitted=exits_submitted,
        )

    # Idempotency/retry guard (see entry_guard.py) — unchanged: a live
    # incident showed auto-execute repeatedly resubmitting a live BUY
    # for the exact same market/outcome every cycle after an unknown/
    # rejected result. Never touches reconciliation's own unknown-fill
    # handling — it only decides whether a NEW submission may happen
    # yet for this exact (condition_id, outcome).
    retry_decision = check_entry_retry_guard(
        pending_store, position_store, condition_id=market.condition_id, outcome=outcome,
        candidate_max_price=max_price, cooldown_seconds=settings.entry_retry_cooldown_seconds,
        min_price_change=settings.entry_retry_min_price_change, now=now,
    )
    if retry_decision.blocked:
        decision_logger.log_decision(
            kind="entry_retry_blocked", reason=retry_decision.reason,
            evidence={
                "condition_id": market.condition_id, "outcome": outcome,
                "candidate_max_price": max_price, "blocking_pending_order_id": retry_decision.blocking_pending_order_id,
            },
        )
        return CycleReport(
            ran=True, market_question=market.question, settled_count=settled, reconciled_count=reconciled,
            exits_submitted=exits_submitted,
        )

    entry_liquidity_usd = order_book.executable_liquidity_usd(side="BUY", max_price=max_price)
    decision_logger.log_decision(
        kind="entry_allowed",
        reason=(
            f"OUTCOME={outcome} YES_ASK={signal.yes_ask} NO_ASK={signal.no_ask} SIZE=${size_usd:.2f} "
            f"REMAINING_SECONDS={seconds_remaining:.0f} ENTRY_DECISION=ALLOW"
        ),
        evidence={
            "condition_id": market.condition_id, "selected_outcome": outcome, "yes_ask": signal.yes_ask,
            "no_ask": signal.no_ask, "actual_allowed_size_usd": size_usd, "remaining_seconds": seconds_remaining,
            "entry_price": order_book.best_ask, "spread": market.yes_spread_pct, "liquidity": entry_liquidity_usd,
            "decision": "ALLOW",
        },
    )

    # Snapshot of exactly what this cycle's own simple entry pipeline
    # computed -- attached to the resulting OpenPosition (see
    # positions.py) so trade_learning.py's RECORD-KEEPING (never its
    # historical-adjustment machinery, which this module never calls)
    # can still journal this decision, whatever is actually available.
    entry_context = {
        "strategy_id": STRATEGY_ID_SIMPLE_PRICE_THRESHOLD,
        "market_question": market.question,
        "yes_ask_at_entry": signal.yes_ask,
        "no_ask_at_entry": signal.no_ask,
        "polymarket_yes_bid": market.yes_bid,
        "polymarket_yes_ask": market.yes_ask,
        "entry_spread": market.yes_spread_pct,
        "entry_liquidity_usd": entry_liquidity_usd,
        "seconds_remaining_at_entry": seconds_remaining,
    }

    order = OrderRequest(
        condition_id=market.condition_id, token_id=token_id, outcome=outcome, side="BUY",
        size_usd=size_usd, max_price=max_price, close_time=market.close_time,
        reason=f"simple_entry: {outcome} ask >= {settings.simple_entry_ask_threshold:.2f}",
        order_type=settings.default_order_type,
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
            entry_context=entry_context,
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
                entry_context=entry_context,
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
