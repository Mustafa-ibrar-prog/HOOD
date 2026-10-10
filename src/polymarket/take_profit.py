"""A simple, fixed +5% take-profit target -- the ONLY automatic exit
logic as of this round, replacing the earlier -20% stop-loss (removed
entirely, never consulted for entry or exit any more), the +20%
trailing stop (trailing_stop.py), and before that the Coinbase-BTC-
evidence-based dynamic exit (exit_manager.py's evaluate_dynamic_exit/
check_and_execute_dynamic_exits). engine.py no longer calls
check_and_execute_trailing_stops() or check_and_execute_dynamic_exits()
in production; those modules (and their own tests) stay in the
codebase unmodified, in case either is wanted again later, but neither
independently sells a position alongside this one (see engine.py's
module docstring).

RULE (verbatim, intentionally simple -- never Coinbase, Chainlink,
RSI, MACD, EMA, BTC momentum, confidence, historical learning, or a
stop-loss):

  1. target_price = position.avg_fill_price * 1.05 (the position's own
     ACTUAL average fill price -- never the requested size, never a
     market-wide reference price). Deterministically re-derived from
     avg_fill_price every time, which is itself already persisted on
     the position -- so target_price is automatically persistent
     across a restart with no separate stored field to go stale or
     drift.
  2. Below the target: HOLD. Never sells merely because the position
     is profitable below +5% (no partial take, no trailing, no
     "close enough"), and never sells on a loss either -- there is no
     stop-loss.
  3. The first time the position's REAL executable value -- the
     CURRENT best bid on its own order book, never the mid, never a
     stale snapshot -- reaches OR EXCEEDS target_price, the position
     is sold in FULL (its entire actual filled share count), once --
     the only automatic exit this strategy ever takes.

P&L is used ONLY to compute target_price from the position's own real
fill price -- it is never consulted as an independent signal.

On a single-order-book venue (Polymarket US -- see single_book.py), a
NO position's "current executable bid" is derived from that venue's
one real book via single_book.to_no_perspective(), never read
directly off it -- see check_and_execute_take_profits() below."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from src.polymarket.exit_retry_guard import check_exit_retry_guard
from src.polymarket.exit_manager import record_exit_fill, reconcile_exit_fill
from src.polymarket.gateway import ExecutionGateway, LivePolymarketGateway, LiveTradingDisabledError, PolymarketOrderPlacer
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import OrderBookSnapshot, OrderRequest, OrderResult
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import OpenPosition, PolymarketPositionStore
from src.polymarket.settings import PolymarketSettings
from src.polymarket.single_book import to_no_perspective
from src.polymarket.state import DailyPnlStateStore
from src.polymarket.trade_learning import CompletedTradeStore

TAKE_PROFIT_MULTIPLE = 1.05

# A fixed, price-scale threshold for exit_retry_guard.check_exit_retry_guard's
# generic "has the candidate value moved enough to justify an immediate
# retry" check -- see trailing_stop.py's own identical constant/
# docstring for why this (not settings.exit_retry_min_evidence_change,
# tuned for a BTC-points scale) is the right threshold here.
_RETRY_MIN_PRICE_CHANGE = 0.01

_ACTION_HOLD = "HOLD"
_ACTION_SELL = "SELL"


@dataclass(frozen=True)
class TakeProfitDecision:
    action: str  # one of the _ACTION_* constants above
    reason: str
    target_price: float  # avg_fill_price * 1.05, always computed, regardless of action
    executable_bid: float | None


def evaluate_take_profit(position: OpenPosition, *, executable_bid: float | None) -> TakeProfitDecision:
    """Pure and side-effect free. `executable_bid` is the CALLER's own
    fresh OrderBookSnapshot.best_bid read for this position's own
    token; None (no bid liquidity at all right now) is always HOLD,
    never a guess. There is no stop-loss -- a losing position is held
    exactly like a merely-profitable-but-sub-target one, until either
    the target is reached or the market resolves."""
    target_price = position.avg_fill_price * TAKE_PROFIT_MULTIPLE

    if executable_bid is None:
        return TakeProfitDecision(_ACTION_HOLD, "no executable bid available this cycle", target_price, None)

    if executable_bid >= target_price:
        return TakeProfitDecision(
            _ACTION_SELL,
            f"executable bid {executable_bid:.4f} reached the +5% target {target_price:.4f} -- full exit",
            target_price, executable_bid,
        )
    return TakeProfitDecision(
        _ACTION_HOLD,
        f"executable bid {executable_bid:.4f} is below the +5% target {target_price:.4f} -- holding",
        target_price, executable_bid,
    )


def submit_take_profit_exit(
    decision: TakeProfitDecision,
    position: OpenPosition,
    *,
    client: Any,
    gateway: ExecutionGateway,
    position_store: PolymarketPositionStore,
    state_store: DailyPnlStateStore,
    decision_logger: PolymarketDecisionLogger,
    settings: PolymarketSettings,
    order_placer: PolymarketOrderPlacer | None = None,
    now: datetime | None = None,
    trade_store: CompletedTradeStore | None = None,
) -> OrderResult:
    """Mirrors exit_manager.submit_dynamic_exit's / trailing_stop.
    submit_trailing_stop_exit's exact mechanics (idempotency-guard-
    before-submit, synchronous reconciliation for paper/same-cycle-live
    fills, exit_retry_guard bookkeeping on a terminal non-fill) -- the
    only thing that's different is WHY this sell was proposed. Caller
    must have already verified `decision.action == "SELL"`; this does
    not re-check it. Sells the position's ACTUAL filled share count in
    FULL, never a partial quantity."""
    now = now or datetime.now(timezone.utc)
    assert decision.action == _ACTION_SELL
    assert decision.executable_bid is not None
    quantity = int(round(position.filled_shares))
    order = OrderRequest(
        condition_id=position.condition_id, token_id=position.token_id, outcome=position.outcome, side="SELL",
        size_usd=round(quantity * decision.executable_bid, 2), max_price=decision.executable_bid,
        close_time=position.close_time, reason="take_profit_exit", order_type=settings.default_order_type,
        quantity=quantity, closes_client_order_id=position.client_order_id,
    )
    result = gateway.submit_order(order)

    pending_order_id = (result.extra or {}).get("pending_order_id")
    if pending_order_id is None and result.fill_result is not None:
        pending_order_id = result.fill_result.order_id

    # pending_exit_edge_points is reused here as "the price level this
    # attempt was submitted under" -- see trailing_stop.py's own
    # identical reuse and its docstring on why this field (named for
    # the OLD BTC-evidence exit system's points scale) is still the
    # right place to stash it: exit_retry_guard.py's mechanism is
    # generic over whatever numeric "has this changed enough" value a
    # caller gives it. Stores the ACTUAL submission-time bid (never a
    # constant like target_price), so a later retry's "has the price
    # moved enough" comparison is against a real prior observation.
    position_store.update(replace(
        position, exit_pending_order_id=pending_order_id, pending_exit_edge_points=decision.executable_bid,
    ))
    decision_logger.log_decision(
        kind="take_profit_exit_submitted",
        reason=f"{position.outcome} on {position.condition_id}: {decision.reason}",
        evidence={
            "position": position.to_dict(), "order": order.to_dict(), "result_status": result.status,
            "target_price": decision.target_price, "executable_bid": decision.executable_bid,
        },
    )

    if (
        result.status == "awaiting_approval" and settings.is_live and settings.auto_exit_enabled
        and order_placer is not None and isinstance(gateway, LivePolymarketGateway)
    ):
        try:
            result = gateway.confirm_and_place(pending_order_id, order_placer, approved_by="system:auto_exit", now=now)
        except LiveTradingDisabledError as exc:
            refreshed = position_store.get(position.client_order_id)
            if refreshed is not None:
                position_store.update(replace(refreshed, exit_pending_order_id=None, pending_exit_edge_points=None))
            decision_logger.log_decision(
                kind="exit_blocked",
                reason=f"Automatic take-profit exit for {position.condition_id} blocked before reaching the exchange: {exc}",
                evidence={"position": position.to_dict()},
            )
            return OrderResult(status="failed", request=order, error=str(exc))

    if result.status == "simulated_fill":
        assert result.fill_result is not None
        record_exit_fill(
            result.fill_result, position, position_store=position_store, state_store=state_store,
            decision_logger=decision_logger, now=now, trade_store=trade_store,
        )
    elif result.status == "submitted":
        exchange_order_id = (result.extra or {}).get("exchange_order_id")
        if exchange_order_id:
            fill = client.get_fill_status(exchange_order_id)
            record_exit_fill(
                fill, position, position_store=position_store, state_store=state_store,
                decision_logger=decision_logger, now=now, trade_store=trade_store,
            )
    elif result.status in ("rejected", "failed"):
        refreshed = position_store.get(position.client_order_id)
        if refreshed is not None and refreshed.exit_pending_order_id == pending_order_id:
            position_store.update(replace(
                refreshed, exit_pending_order_id=None, pending_exit_edge_points=None,
                last_exit_attempt_at=now, last_exit_attempt_edge_points=refreshed.pending_exit_edge_points,
            ))
    # result.status == "awaiting_approval": exit_pending_order_id stays
    # set -- a human confirm_and_place() call, or a later
    # reconcile_exit_fill() sweep, picks this up. Never assumed filled.

    return result


def check_and_execute_take_profits(
    *,
    client: Any,
    settings: PolymarketSettings,
    gateway: ExecutionGateway,
    position_store: PolymarketPositionStore,
    pending_store: PolymarketPendingOrderStore,
    state_store: DailyPnlStateStore,
    decision_logger: PolymarketDecisionLogger,
    trade_store: CompletedTradeStore | None = None,
    skip_client_order_ids: frozenset[str] = frozenset(),
    now: datetime | None = None,
) -> int:
    """One per-cycle pass over every open position -- the production
    exit check, called from engine.run_cycle() right after
    settle_resolved_positions() and BEFORE any new-entry evaluation.
    There is no master switch/settings flag here -- this strategy's
    exit logic is unconditionally part of the production path.

    For each open position:
      1. a position with an exit already pending is swept via
         exit_manager.reconcile_exit_fill() (restart-safe; reused
         unmodified -- recording a real fill is side-agnostic
         plumbing, not strategy-specific logic);
      2. a position whose own market has already closed is skipped
         entirely (settle_resolved_positions(), already run earlier
         this same cycle, is the correct, exchange-aware path for a
         closed market -- never a fresh SELL attempt into one that's
         no longer open);
      3. otherwise, a FRESH order book is fetched for this position's
         own token and evaluate_take_profit() decides HOLD/SELL from
         ONLY this position's own avg_fill_price and the current
         executable bid.

    `skip_client_order_ids` mirrors the DELAYED-ENTRY GRACE parameter
    the earlier exit systems in this package already use -- a position
    adopted via a delayed reconcile_pending_orders() sweep THIS SAME
    cycle is deferred one cycle, for the same restart-safety reason.

    Returns the number of exit orders submitted this call."""
    now = now or datetime.now(timezone.utc)
    order_placer = client if settings.is_live else None
    submitted = 0

    for snapshot in position_store.load():
        current = position_store.get(snapshot.client_order_id)
        if current is None:
            continue

        if current.client_order_id in skip_client_order_ids:
            decision_logger.log_decision(
                kind="exit_check_deferred",
                reason=(
                    f"{current.outcome} on {current.condition_id}: position was just adopted via a delayed "
                    "entry-order reconciliation THIS cycle -- deferring take-profit evaluation one cycle"
                ),
                evidence={"position": current.to_dict()},
            )
            continue

        if current.exit_pending_order_id is not None:
            reconcile_exit_fill(
                current, client=client, pending_store=pending_store, position_store=position_store,
                state_store=state_store, decision_logger=decision_logger, now=now, trade_store=trade_store,
            )
            continue

        close_time = current.close_time if current.close_time.tzinfo else current.close_time.replace(tzinfo=timezone.utc)
        if now >= close_time:
            decision_logger.log_decision(
                kind="exit_check_skipped_market_closed",
                reason=(
                    f"{current.outcome} on {current.condition_id}: this position's market already closed "
                    f"({close_time.isoformat()}) -- deferring entirely to settlement"
                ),
                evidence={"position": current.to_dict()},
            )
            continue

        try:
            order_book: OrderBookSnapshot = client.get_order_book(current.token_id)
        except Exception as exc:  # noqa: BLE001 - a book-fetch failure must never crash the bot or be treated as "no change"
            decision_logger.log_decision(
                kind="exit_check_failed",
                reason=f"Could not fetch order book for {current.condition_id}: {exc}",
                evidence={"position": current.to_dict()},
            )
            continue

        # On a single-order-book venue (Polymarket US -- see
        # single_book.py), current.token_id is the SAME single book
        # regardless of outcome, priced on the YES axis. A NO position's
        # own "current executable bid" (what closing it right now would
        # realize) is never that raw book's own best_bid -- it is the
        # NO-perspective derivation's best_bid (1 - the raw book's
        # best_ask -- see to_no_perspective's docstring). On a
        # genuinely two-book venue (international Polymarket), or for a
        # YES position on either venue, the raw book already IS this
        # outcome's own real book -- no conversion.
        if current.outcome == "NO" and current.single_book_market:
            order_book = to_no_perspective(order_book)

        decision = evaluate_take_profit(current, executable_bid=order_book.best_bid)

        if decision.action == _ACTION_HOLD:
            decision_logger.log_decision(
                kind="take_profit_hold",
                reason=f"{current.outcome} on {current.condition_id}: {decision.reason}",
                evidence={"position": current.to_dict(), "target_price": decision.target_price},
            )
            continue

        # SELL -- rate-limited by exit_retry_guard.py exactly like the
        # earlier exit systems (a recently-failed attempt must either
        # wait out its cooldown or see the price move enough to retry
        # immediately).
        retry_decision = check_exit_retry_guard(
            current, candidate_btc_points=decision.executable_bid or 0.0,
            cooldown_seconds=settings.exit_retry_cooldown_seconds, min_evidence_change=_RETRY_MIN_PRICE_CHANGE, now=now,
        )
        if retry_decision.blocked:
            decision_logger.log_decision(
                kind="take_profit_retry_blocked",
                reason=f"{current.outcome} on {current.condition_id}: {retry_decision.reason}",
                evidence={"position": current.to_dict()},
            )
            continue

        submit_take_profit_exit(
            decision, current, client=client, gateway=gateway, position_store=position_store,
            state_store=state_store, decision_logger=decision_logger, settings=settings,
            order_placer=order_placer, now=now, trade_store=trade_store,
        )
        submitted += 1

    return submitted
