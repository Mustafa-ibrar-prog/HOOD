"""Automatic profit-target exit for an open Polymarket US position — the
first EARLY-exit path in this codebase alongside hold-to-resolution
settlement (engine.settle_resolved_positions), which remains the
fallback whenever a position's target is never reached before its
market closes. Nothing here alters settlement, risk.py's entry checks,
or the existing BUY path in any way.

TWO DIFFERENT STEPS, NOT A CONTRADICTION — trigger vs. recording:
  - WHETHER to exit is decided purely from the live order book's best
    BID against a GROSS target price:
        target_price = avg_fill_price * (1 + profit_target_pct)
    (see compute_target_price) — e.g. a $0.36 average fill with the
    default 0.20 target gives target_price ≈ $0.432, BEFORE accounting
    for exit fees. This can only ever be checked against real,
    currently-executable bid liquidity — never the ask or the
    midpoint, since this system can only SELL into a resting bid, not
    cross its own spread.
  - the REALIZED P&L this module records once an exit actually fills
    (record_exit_fill) is always NET of both entry and exit fees
    whenever the exchange reports them (FillResult.fee_usd) — never an
    assumption that a 20% gross price move alone made the trade
    profitable.

IDEMPOTENCY — the same two-independent-guards philosophy
reconciliation.py already established for entries, applied to exits:
  1. OpenPosition.exit_pending_order_id is the PRIMARY guard: set the
     instant an exit order is submitted (submit_profit_target_exit),
     checked before any new exit is ever proposed
     (evaluate_profit_target_exit/check_and_execute_profit_target_exits).
     Persisted on disk — restart-safe by construction, not an
     in-memory flag.
  2. PolymarketPendingOrderStore's own per-id semantics are the
     secondary guard on the live side (same store entries already use).
  An exit fill status of "unknown" leaves exit_pending_order_id SET —
  never cleared, never assumed filled — so a later sweep
  (reconcile_exit_fill) retries the SAME lookup instead of ever
  proposing a second, duplicate exit for the same position.

LIVE SUBMISSION, EMERGENCY STOP: an automatic exit that reaches the
exchange in live mode goes through the EXACT SAME
LivePolymarketGateway.confirm_and_place() -> _submit_pending() path
entries use, so it inherits that method's independent, pre-existing
emergency-stop check for free — there is no separate emergency-stop
check in this module, by design, so the two paths can never drift
apart. settings.auto_exit_enabled (default False) is a SEPARATE,
exit-specific switch, independent of settings.live_auto_execute (the
entry-only flag — left untouched, never enabled by this module): it
only ever decides whether a LIVE exit that reached its profit target
is immediately confirmed and placed, or stops at awaiting_approval for
a human to confirm (scripts/confirm_pending_order.py and
scripts/confirm_polymarket_order.py already handle this generically,
regardless of the underlying order's side). PAPER mode is unaffected
by auto_exit_enabled either way — gateway.submit_order() already
returns a synthetic, immediate fill in paper mode regardless, exactly
like an entry, and (also exactly like an entry) is never blocked by
emergency stop — paper mode never touches real money or the real
order placer.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from src.polymarket.gateway import ExecutionGateway, LivePolymarketGateway, LiveTradingDisabledError, PolymarketOrderPlacer
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import FillResult, OrderBookSnapshot, OrderRequest, OrderResult
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import OpenPosition, PolymarketPositionStore
from src.polymarket.settings import PolymarketSettings
from src.polymarket.state import DailyPnlStateStore


def compute_target_price(avg_fill_price: float, profit_target_pct: float) -> float:
    """The GROSS trigger price for a LONG/YES position:
    avg_fill_price * (1 + profit_target_pct) — e.g. $0.36 * 1.20 ≈
    $0.432 with the default 0.20 target. Deliberately based on the
    position's own ACTUAL average fill price (never the requested
    order size or a suggested entry price) — see OpenPosition's
    docstring: avg_fill_price already is that verified figure.

    Rounded to 4 decimal places, matching models.OrderBookSnapshot's
    own mid/spread_pct convention — precise enough to compare against
    a real bid price, far from the floating-point noise of the raw
    multiplication (0.36 * 1.2 == 0.43200000000000005 in IEEE 754)."""
    return round(avg_fill_price * (1.0 + profit_target_pct), 4)


@dataclass(frozen=True)
class ExitDecision:
    """The full, inspectable answer to "should this position exit right
    now," independent of whether anything is actually submitted —
    evaluate_profit_target_exit() is pure and side-effect free; only
    submit_profit_target_exit() (called separately, only when
    `eligible`) ever touches the network or the position ledger."""

    position: OpenPosition
    eligible: bool
    reason: str
    target_price: float
    best_bid: float | None
    executable_shares_at_target: float


def evaluate_profit_target_exit(
    position: OpenPosition, order_book: OrderBookSnapshot, *, profit_target_pct: float,
) -> ExitDecision:
    """Pure decision logic — requirement checklist, in order:
      1. no exit already pending for this position (idempotency guard);
      2. the REAL live best BID (never the ask, never the midpoint) has
         reached the GROSS target price;
      3. there is enough REAL executable bid liquidity, AT OR ABOVE the
         target price, to sell the position's entire filled_shares.
    Any failure returns `eligible=False` with a human-readable reason;
    nothing here ever submits an order."""
    target_price = compute_target_price(position.avg_fill_price, profit_target_pct)
    best_bid = order_book.best_bid

    if position.exit_pending_order_id is not None:
        return ExitDecision(
            position=position, eligible=False,
            reason=f"An exit order ({position.exit_pending_order_id}) is already pending for this position",
            target_price=target_price, best_bid=best_bid, executable_shares_at_target=0.0,
        )

    if best_bid is None or best_bid < target_price:
        return ExitDecision(
            position=position, eligible=False,
            reason=f"Best bid ({best_bid}) has not reached the profit target ({target_price})",
            target_price=target_price, best_bid=best_bid, executable_shares_at_target=0.0,
        )

    available = order_book.executable_shares(side="SELL", min_price=target_price)
    if available < position.filled_shares:
        return ExitDecision(
            position=position, eligible=False,
            reason=(
                f"Insufficient executable bid liquidity at/above target {target_price}: "
                f"{available} available shares < {position.filled_shares} needed"
            ),
            target_price=target_price, best_bid=best_bid, executable_shares_at_target=available,
        )

    return ExitDecision(
        position=position, eligible=True,
        reason=f"Best bid {best_bid} >= target {target_price} with sufficient bid liquidity ({available} shares)",
        target_price=target_price, best_bid=best_bid, executable_shares_at_target=available,
    )


def _fill_to_dict(fill: FillResult) -> dict:
    return {
        "order_id": fill.order_id, "status": fill.status, "requested_shares": fill.requested_shares,
        "filled_shares": fill.filled_shares, "avg_fill_price": fill.avg_fill_price, "fee_usd": fill.fee_usd,
    }


def record_exit_fill(
    fill: FillResult,
    position: OpenPosition,
    *,
    position_store: PolymarketPositionStore,
    state_store: DailyPnlStateStore,
    decision_logger: PolymarketDecisionLogger,
    now: datetime,
) -> OpenPosition | None:
    """The ONLY place an exit FillResult mutates the position ledger —
    the exit-side counterpart to reconciliation.record_fill(). Always
    re-reads the CURRENT persisted position by client_order_id first
    (never trusts the possibly-stale `position` argument for anything
    but its identity key), so this is safe to call more than once for
    the same fill: a second call finds the position already
    gone/updated and no-ops.

    Returns the updated (still-open, partially-closed) OpenPosition, or
    None if the position is now fully closed or there was nothing to
    do."""
    current = position_store.get(position.client_order_id)
    if current is None:
        return None  # already fully closed by an earlier call -- nothing to do

    if fill.status == "unknown":
        # NOT an authoritative determination -- requirement: "if exit
        # status is unknown, STOP and retry reconciliation later; never
        # assume an exit filled." exit_pending_order_id is left exactly
        # as it is, so a later sweep (reconcile_exit_fill) re-checks the
        # SAME exit rather than this position ever being offered a
        # second, duplicate one.
        decision_logger.log_decision(
            kind="exit_status_unknown",
            reason=f"Exit order {fill.order_id} for {current.condition_id}: status unknown, "
                   "position left unchanged, NOT reconciled -- re-checkable later",
            evidence={"position": current.to_dict(), "fill": _fill_to_dict(fill)},
        )
        return current

    if not fill.is_fill:
        # A genuine terminal non-fill (rejected/cancelled/expired), or a
        # resting state that should never actually happen for an
        # IOC/FOK exit -- authoritative and safe to clear: free to
        # retry a fresh exit next cycle, nothing about the position
        # itself changed.
        cleared = replace(current, exit_pending_order_id=None)
        position_store.update(cleared)
        decision_logger.log_decision(
            kind="exit_not_filled",
            reason=f"Exit order {fill.order_id} for {current.condition_id}: {fill.status}, position unchanged",
            evidence={"position": current.to_dict(), "fill": _fill_to_dict(fill)},
        )
        return cleared

    # A real (full or partial) fill. Reconcile EXACTLY how much of the
    # position this exit closed -- never assume full (requirement:
    # "reconcile the partial fill correctly and leave only the
    # remaining quantity open").
    closed_shares = fill.filled_shares
    remaining_shares = max(0.0, round(current.filled_shares - closed_shares, 8))
    exit_fee = fill.fee_usd or 0.0
    entry_fee_for_closed = (
        current.entry_fee_usd * (closed_shares / current.filled_shares) if current.filled_shares else 0.0
    )
    # NET realized P&L on the closed slice only -- proceeds at the
    # ACTUAL average exit price, minus the matching slice of the
    # original entry cost, minus BOTH entry and exit fees whenever the
    # exchange actually reported them. Never inferred from the gross
    # 20% price move alone (requirement: "Do not call a trade
    # profitable merely because gross price increased 20%").
    proceeds = closed_shares * fill.avg_fill_price
    entry_cost_for_closed = closed_shares * current.avg_fill_price
    realized_pnl = proceeds - entry_cost_for_closed - entry_fee_for_closed - exit_fee

    state = state_store.load(today=now.date())
    state.realized_pnl_usd += realized_pnl
    fully_closed = remaining_shares <= 1e-6
    if fully_closed:
        state.open_position_count = max(0, state.open_position_count - 1)
        state.last_exit_time = now.isoformat()
    state_store.save(state)

    decision_logger.log_decision(
        kind="profit_target_exit_filled",
        reason=(
            f"{current.outcome} on {current.condition_id}: exit "
            f"{'FULLY' if fully_closed else 'PARTIALLY'} filled {closed_shares:.4f}/{current.filled_shares:.4f} "
            f"shares @ ${fill.avg_fill_price:.4f}, realized_pnl=${realized_pnl:.4f} "
            f"(entry_fee=${entry_fee_for_closed:.4f}, exit_fee=${exit_fee:.4f})"
        ),
        evidence={
            "position": current.to_dict(), "fill": _fill_to_dict(fill), "realized_pnl_usd": realized_pnl,
            "entry_fee_usd": entry_fee_for_closed, "exit_fee_usd": exit_fee,
        },
    )

    if fully_closed:
        position_store.remove(current.condition_id)
        return None

    updated = replace(
        current, filled_shares=remaining_shares, exit_pending_order_id=None,
        entry_fee_usd=max(0.0, current.entry_fee_usd - entry_fee_for_closed),
    )
    position_store.update(updated)
    return updated


def reconcile_exit_fill(
    position: OpenPosition,
    *,
    client: Any,
    pending_store: PolymarketPendingOrderStore,
    position_store: PolymarketPositionStore,
    state_store: DailyPnlStateStore,
    decision_logger: PolymarketDecisionLogger,
    now: datetime | None = None,
) -> OpenPosition | None:
    """The restart-safety sweep for a position whose exit_pending_order_id
    is already set — the exit-side counterpart to
    reconciliation.reconcile_pending_orders(). Safe to call any number
    of times, including across a process restart: every check here is
    against persisted state, never in-memory flags.

    No-ops (returns `position` unchanged) when there is genuinely
    nothing new to learn yet: a paper-mode fill is always reconciled
    synchronously by submit_profit_target_exit() the moment it happens,
    so exit_pending_order_id should never outlive that single call for
    paper mode; reaching here with no matching PendingLiveOrder (or one
    that hasn't reached the exchange yet, still awaiting a human
    confirm_and_place()) means there's nothing more this sweep can
    learn right now."""
    now = now or datetime.now(timezone.utc)
    if position.exit_pending_order_id is None:
        return position

    pending = pending_store.get(position.exit_pending_order_id)
    if pending is None or pending.exchange_order_id is None:
        return position

    fill = client.get_fill_status(pending.exchange_order_id)
    return record_exit_fill(
        fill, position, position_store=position_store, state_store=state_store, decision_logger=decision_logger, now=now,
    )


def submit_profit_target_exit(
    decision: ExitDecision,
    *,
    client: Any,
    gateway: ExecutionGateway,
    position_store: PolymarketPositionStore,
    state_store: DailyPnlStateStore,
    decision_logger: PolymarketDecisionLogger,
    settings: PolymarketSettings,
    order_placer: PolymarketOrderPlacer | None = None,
    now: datetime | None = None,
) -> OrderResult:
    """Submits the exit order for an ELIGIBLE decision, marks the
    position's exit_pending_order_id BEFORE anything else can observe
    it (the idempotency guard), and — for every outcome this call can
    fully resolve synchronously (a paper-mode simulated fill, or a
    live order that reached the exchange this same call) — reconciles
    it immediately, exactly mirroring how engine.run_cycle() already
    handles the symmetric cases on the entry side.

    Caller (check_and_execute_profit_target_exits) must have already
    verified `decision.eligible`; this does not re-check eligibility
    itself."""
    position = decision.position
    now = now or datetime.now(timezone.utc)
    quantity = int(round(position.filled_shares))
    order = OrderRequest(
        condition_id=position.condition_id, token_id=position.token_id, outcome=position.outcome, side="SELL",
        size_usd=round(quantity * decision.target_price, 2), max_price=decision.target_price,
        close_time=position.close_time, reason="profit_target_exit", order_type=settings.default_order_type,
        quantity=quantity, closes_client_order_id=position.client_order_id,
    )
    result = gateway.submit_order(order)

    pending_order_id = (result.extra or {}).get("pending_order_id")
    if pending_order_id is None and result.fill_result is not None:
        pending_order_id = result.fill_result.order_id  # paper mode's synthetic id -- same idempotency role

    position_store.update(replace(position, exit_pending_order_id=pending_order_id))
    decision_logger.log_decision(
        kind="profit_target_exit_submitted",
        reason=(
            f"{position.outcome} on {position.condition_id}: submitting exit for {quantity} shares at a minimum "
            f"of ${decision.target_price} (best_bid was {decision.best_bid})"
        ),
        evidence={"position": position.to_dict(), "order": order.to_dict(), "result_status": result.status},
    )

    if (
        result.status == "awaiting_approval" and settings.is_live and settings.auto_exit_enabled
        and order_placer is not None and isinstance(gateway, LivePolymarketGateway)
    ):
        try:
            result = gateway.confirm_and_place(pending_order_id, order_placer, approved_by="system:auto_exit", now=now)
        except LiveTradingDisabledError as exc:
            # Emergency stop (or a live/confirmed flag flip) blocked
            # this exit before it ever reached the exchange. The
            # underlying PendingLiveOrder is now a terminal "failed"
            # with no exchange_order_id -- nothing to reconcile -- so
            # this position must NOT stay permanently exit-blocked:
            # clear the guard so a later cycle can re-propose a fresh
            # exit once the block lifts. "Emergency stop blocks
            # automatic exits," not "...forever."
            refreshed = position_store.get(position.client_order_id)
            if refreshed is not None:
                position_store.update(replace(refreshed, exit_pending_order_id=None))
            decision_logger.log_decision(
                kind="exit_blocked",
                reason=f"Automatic exit for {position.condition_id} blocked before reaching the exchange: {exc}",
                evidence={"position": position.to_dict()},
            )
            return OrderResult(status="failed", request=order, error=str(exc))

    if result.status == "simulated_fill":
        assert result.fill_result is not None
        record_exit_fill(
            result.fill_result, position, position_store=position_store, state_store=state_store,
            decision_logger=decision_logger, now=now,
        )
    elif result.status == "submitted":
        exchange_order_id = (result.extra or {}).get("exchange_order_id")
        if exchange_order_id:
            fill = client.get_fill_status(exchange_order_id)
            record_exit_fill(
                fill, position, position_store=position_store, state_store=state_store,
                decision_logger=decision_logger, now=now,
            )
    elif result.status in ("rejected", "failed"):
        # Terminal, no-position-change outcomes with nothing to wait
        # on -- free the guard so a later cycle can retry.
        refreshed = position_store.get(position.client_order_id)
        if refreshed is not None and refreshed.exit_pending_order_id == pending_order_id:
            position_store.update(replace(refreshed, exit_pending_order_id=None))
    # result.status == "awaiting_approval": exit_pending_order_id stays
    # set -- a human confirm_and_place() call (scripts/confirm_pending_order.py
    # or confirm_polymarket_order.py, both already side-agnostic), or a
    # later reconcile_exit_fill() sweep once one happens, picks this up.
    # Never assumed filled.

    return result


def check_and_execute_profit_target_exits(
    *,
    client: Any,
    settings: PolymarketSettings,
    gateway: ExecutionGateway,
    position_store: PolymarketPositionStore,
    pending_store: PolymarketPendingOrderStore,
    state_store: DailyPnlStateStore,
    decision_logger: PolymarketDecisionLogger,
    now: datetime | None = None,
) -> int:
    """One per-cycle pass over every open position — intended to be
    called from engine.run_cycle() right after settle_resolved_positions()
    and before any new-entry evaluation, exactly like that function's
    own reconciliation sweep. For each position:
      1. a position with an exit already pending is swept via
         reconcile_exit_fill() (restart-safe; never proposes a second
         exit while one is in flight or of unknown status);
      2. otherwise, a FRESH order book is fetched (never a cached/stale
         snapshot — requirement: re-verify live, right before acting)
         and evaluate_profit_target_exit() decides eligibility;
      3. an eligible position gets exactly one exit order submitted via
         submit_profit_target_exit().

    Returns the number of exit orders submitted this call (0 is the
    overwhelmingly common case: most cycles, no position has reached
    its target)."""
    now = now or datetime.now(timezone.utc)
    order_placer = client if settings.is_live else None
    submitted = 0

    for snapshot in position_store.load():
        # Re-fetch by client_order_id rather than trust this loop's own
        # snapshot — an earlier iteration (or a concurrent process)
        # could have already mutated or closed it (requirement:
        # "verify the position still exists").
        current = position_store.get(snapshot.client_order_id)
        if current is None:
            continue

        if current.exit_pending_order_id is not None:
            reconcile_exit_fill(
                current, client=client, pending_store=pending_store, position_store=position_store,
                state_store=state_store, decision_logger=decision_logger, now=now,
            )
            continue

        try:
            order_book = client.get_order_book(current.token_id)
        except Exception as exc:  # noqa: BLE001 - a book-fetch failure must never be treated as "target reached"
            decision_logger.log_decision(
                kind="exit_check_failed",
                reason=f"Could not fetch order book for {current.condition_id}: {exc}",
                evidence={"position": current.to_dict()},
            )
            continue

        decision = evaluate_profit_target_exit(current, order_book, profit_target_pct=settings.profit_target_pct)
        if not decision.eligible:
            continue

        submit_profit_target_exit(
            decision, client=client, gateway=gateway, position_store=position_store, state_store=state_store,
            decision_logger=decision_logger, settings=settings, order_placer=order_placer, now=now,
        )
        submitted += 1

    return submitted
