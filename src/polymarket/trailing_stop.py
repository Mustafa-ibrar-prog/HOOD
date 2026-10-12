"""A simple +20% profit trailing stop -- the ONLY production exit
logic as of this round, replacing the Coinbase-BTC-evidence-based
dynamic exit (exit_manager.py's evaluate_dynamic_exit/
check_and_execute_dynamic_exits) entirely. engine.py no longer calls
exit_manager.check_and_execute_dynamic_exits() in production; that
module (and its own tests) stays in the codebase unmodified, in case
it is wanted again later, but it no longer independently sells a
position alongside this one (see engine.py's module docstring).

RULE (verbatim, intentionally simple -- never Coinbase, Chainlink,
RSI, MACD, EMA, BTC momentum, confidence, or historical learning):

  1. floor_price = position.avg_fill_price * 1.20 (the position's own
     ACTUAL average fill price -- never the requested size, never a
     market-wide reference price).
  2. The stop is NOT active (armed) immediately on entry.
  3. The first time the position's REAL executable value -- the
     CURRENT best bid on its own order book, never the mid, never a
     stale snapshot -- reaches AT LEAST floor_price, the stop ARMS.
     Arming itself is never a sell.
  4. Once armed, the position is held regardless of how far the price
     rises above the floor (this module never sells "because +20% was
     reached" -- only evaluate_trailing_stop's SELL branch, below,
     ever recommends a sell).
  5. Once armed, the position is sold in FULL the next time the
     executable bid falls back to (<=) floor_price.

P&L is used ONLY to compute floor_price from the position's own real
fill price -- it is never consulted as an independent signal (2A/13
in the governing instructions)."""

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
from src.polymarket.state import DailyPnlStateStore
from src.polymarket.trade_learning import CompletedTradeStore

ACTIVATION_MULTIPLE = 1.20

# A fixed, price-scale threshold for exit_retry_guard.check_exit_retry_guard's
# generic "has the candidate value moved enough to justify an immediate
# retry" check -- reused unmodified from the BTC-evidence exit system
# (which measures its own candidate in BTC evidence points, a
# completely different scale), so this is deliberately NOT
# settings.exit_retry_min_evidence_change (tuned for that other
# scale). One cent is a reasonable "the market actually moved"
# threshold for a 0-1 priced token.
_RETRY_MIN_PRICE_CHANGE = 0.01

_ACTION_HOLD = "HOLD"
_ACTION_ARM = "ARM"
_ACTION_UPDATE_PEAK = "UPDATE_PEAK"
_ACTION_SELL = "SELL"


@dataclass(frozen=True)
class TrailingStopDecision:
    action: str  # one of the _ACTION_* constants above
    reason: str
    floor_price: float  # avg_fill_price * 1.20, always computed, regardless of action
    executable_bid: float | None
    new_peak_price: float | None  # the peak to persist on ARM/UPDATE_PEAK; None otherwise


def evaluate_trailing_stop(position: OpenPosition, *, executable_bid: float | None) -> TrailingStopDecision:
    """Pure and side-effect free -- callers persist whatever this
    recommends. `executable_bid` is the CALLER's own fresh
    OrderBookSnapshot.best_bid read for this position's own token;
    None (no bid liquidity at all right now) is always HOLD, never a
    guess."""
    floor_price = position.avg_fill_price * ACTIVATION_MULTIPLE

    if executable_bid is None:
        return TrailingStopDecision(_ACTION_HOLD, "no executable bid available this cycle", floor_price, None, None)

    if not position.trailing_stop_armed:
        if executable_bid >= floor_price:
            return TrailingStopDecision(
                _ACTION_ARM,
                f"executable bid {executable_bid:.4f} reached the +20% floor {floor_price:.4f} -- arming trailing stop "
                "(this is never itself a sell)",
                floor_price, executable_bid, executable_bid,
            )
        return TrailingStopDecision(
            _ACTION_HOLD,
            f"executable bid {executable_bid:.4f} is below the +20% floor {floor_price:.4f} -- not yet armed",
            floor_price, executable_bid, None,
        )

    # Armed: sell only when price falls back TO (<=) the floor; otherwise
    # keep riding, tracking the peak purely for visibility/auditability
    # (the floor itself never trails upward -- requirement 5: "keep the
    # stop floor at +20% above the original average fill price").
    current_peak = position.trailing_stop_peak_price if position.trailing_stop_peak_price is not None else floor_price
    if executable_bid <= floor_price:
        return TrailingStopDecision(
            _ACTION_SELL,
            f"executable bid {executable_bid:.4f} fell back to the +20% floor {floor_price:.4f} "
            f"(peak was {current_peak:.4f}) -- full exit",
            floor_price, executable_bid, None,
        )
    if executable_bid > current_peak:
        return TrailingStopDecision(
            _ACTION_UPDATE_PEAK,
            f"new peak {executable_bid:.4f}, still above the +20% floor {floor_price:.4f} -- holding, letting it ride",
            floor_price, executable_bid, executable_bid,
        )
    return TrailingStopDecision(
        _ACTION_HOLD,
        f"executable bid {executable_bid:.4f} above the +20% floor {floor_price:.4f} (peak {current_peak:.4f}) -- holding",
        floor_price, executable_bid, None,
    )


def submit_trailing_stop_exit(
    decision: TrailingStopDecision,
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
    """Mirrors exit_manager.submit_dynamic_exit's exact mechanics
    (idempotency-guard-before-submit, synchronous reconciliation for
    paper/same-cycle-live fills, exit_retry_guard bookkeeping on a
    terminal non-fill) -- the only thing that's different is WHY this
    sell was proposed. Caller must have already verified
    `decision.action == "SELL"`; this does not re-check it."""
    now = now or datetime.now(timezone.utc)
    assert decision.action == _ACTION_SELL
    assert decision.executable_bid is not None
    quantity = int(round(position.filled_shares))
    order = OrderRequest(
        condition_id=position.condition_id, token_id=position.token_id, outcome=position.outcome, side="SELL",
        size_usd=round(quantity * decision.executable_bid, 2), max_price=decision.executable_bid,
        close_time=position.close_time, reason="trailing_stop_exit", order_type=settings.default_order_type,
        quantity=quantity, closes_client_order_id=position.client_order_id,
    )
    result = gateway.submit_order(order)

    pending_order_id = (result.extra or {}).get("pending_order_id")
    if pending_order_id is None and result.fill_result is not None:
        pending_order_id = result.fill_result.order_id

    # pending_exit_edge_points is reused here as "the floor price this
    # attempt was submitted under" -- see this module's own
    # _RETRY_MIN_PRICE_CHANGE docstring on why that field (named for
    # the OTHER exit system's BTC-points scale) is still the right
    # place to stash it: exit_retry_guard.py's mechanism is generic
    # over whatever numeric "has this changed enough" value a caller
    # gives it.
    position_store.update(replace(
        position, exit_pending_order_id=pending_order_id, pending_exit_edge_points=decision.floor_price,
    ))
    decision_logger.log_decision(
        kind="trailing_stop_exit_submitted",
        reason=f"{position.outcome} on {position.condition_id}: {decision.reason}",
        evidence={
            "position": position.to_dict(), "order": order.to_dict(), "result_status": result.status,
            "floor_price": decision.floor_price, "executable_bid": decision.executable_bid,
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
                reason=f"Automatic trailing-stop exit for {position.condition_id} blocked before reaching the exchange: {exc}",
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


def check_and_execute_trailing_stops(
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
    settle_resolved_positions() and BEFORE any new-entry evaluation,
    exactly where exit_manager.check_and_execute_dynamic_exits() used
    to run (see engine.py's module docstring). There is no master
    switch/settings flag here (unlike dynamic_exit_enabled) -- this
    strategy's exit logic is unconditionally part of the production
    path as of this round.

    For each open position:
      1. a position with an exit already pending is swept via
         exit_manager.reconcile_exit_fill() (restart-safe; reused
         unmodified -- recording a real fill is side-agnostic
         plumbing, not "BTC evidence logic");
      2. a position whose own market has already closed is skipped
         entirely (settle_resolved_positions(), already run earlier
         this same cycle, is the correct, exchange-aware path for a
         closed market -- never a fresh SELL attempt into one that's
         no longer open);
      3. otherwise, a FRESH order book is fetched for this position's
         own token and evaluate_trailing_stop() decides ARM/HOLD/
         UPDATE_PEAK/SELL from ONLY this position's own avg_fill_price
         and the current executable bid.

    `skip_client_order_ids` mirrors check_and_execute_dynamic_exits'
    own DELAYED-ENTRY GRACE parameter -- a position adopted via a
    delayed reconcile_pending_orders() sweep THIS SAME cycle is
    deferred one cycle, for the same restart-safety reason.

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
                    "entry-order reconciliation THIS cycle -- deferring trailing-stop evaluation one cycle"
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

        decision = evaluate_trailing_stop(current, executable_bid=order_book.best_bid)

        if decision.action == _ACTION_HOLD:
            decision_logger.log_decision(
                kind="trailing_stop_hold",
                reason=f"{current.outcome} on {current.condition_id}: {decision.reason}",
                evidence={"position": current.to_dict(), "floor_price": decision.floor_price},
            )
            continue

        if decision.action in (_ACTION_ARM, _ACTION_UPDATE_PEAK):
            position_store.update(replace(
                current, trailing_stop_armed=True, trailing_stop_peak_price=decision.new_peak_price,
            ))
            decision_logger.log_decision(
                kind="trailing_stop_armed" if decision.action == _ACTION_ARM else "trailing_stop_peak_updated",
                reason=f"{current.outcome} on {current.condition_id}: {decision.reason}",
                evidence={
                    "position": current.to_dict(), "floor_price": decision.floor_price,
                    "peak_price": decision.new_peak_price,
                },
            )
            continue

        # SELL -- rate-limited by exit_retry_guard.py exactly like the
        # old BTC-evidence exit system (a recently-failed attempt must
        # either wait out its cooldown or see the price move enough to
        # retry immediately).
        retry_decision = check_exit_retry_guard(
            current, candidate_btc_points=decision.executable_bid or 0.0,
            cooldown_seconds=settings.exit_retry_cooldown_seconds, min_evidence_change=_RETRY_MIN_PRICE_CHANGE, now=now,
        )
        if retry_decision.blocked:
            decision_logger.log_decision(
                kind="trailing_stop_retry_blocked",
                reason=f"{current.outcome} on {current.condition_id}: {retry_decision.reason}",
                evidence={"position": current.to_dict()},
            )
            continue

        submit_trailing_stop_exit(
            decision, current, client=client, gateway=gateway, position_store=position_store,
            state_store=state_store, decision_logger=decision_logger, settings=settings,
            order_placer=order_placer, now=now, trade_store=trade_store,
        )
        submitted += 1

    return submitted
