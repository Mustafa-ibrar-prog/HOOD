"""Bounded re-entry/retry guard for NEW (BUY) order submissions —
mirrors exit_manager.py's exit_pending_order_id idempotency philosophy
on the entry side, which had no equivalent until a live incident
exposed the gap:

    order_status_unknown -> rejected -> new pending_order
    (repeats on the same 15-minute market every cycle)

reconciliation.py's unknown-fill handling was already correct (it never
fabricates a fill — see its own module docstring), but nothing
upstream of it stopped engine.run_cycle() from proposing and
submitting ANOTHER live BUY for the exact same market/outcome on the
very next cycle: a failed/unknown attempt never touches
state.open_position_count (no position was ever created), so
risk.py's MAX_OPEN_POSITIONS check has nothing to block. This module
closes that gap WITHOUT touching risk.py, reconciliation.py, or the
unknown-fill safety at all — it is a separate, additive gate engine.py
consults right before building/submitting a new entry order.

Two distinct cases, matched to the user's own description
("unresolved OR recently failed"):

  1. UNRESOLVED — the most recent entry attempt for this exact
     (condition_id, outcome) is still awaiting_approval (a human
     hasn't decided), or was submitted and not yet reconciled (fill
     status unknown, or simply not checked yet this cycle). ALWAYS
     blocks a new submission, with NO time limit and NO price-change
     escape — proposing a second entry while the first is still live
     or of genuinely unknown outcome is exactly the duplicate-exposure
     risk this guard exists to prevent. Once a later reconciliation
     sweep resolves it (fill, or an authoritative non-fill), this
     guard re-evaluates fresh on the next cycle.

  2. RECENTLY FAILED — the most recent attempt reconciled (or was
     rejected/expired/failed outright) with NO resulting position.
     Blocks for config.cooldown_seconds UNLESS the entry price has
     moved by at least config.min_price_change since that attempt —
     "require a materially changed entry condition before retrying."
     A different outcome (YES vs NO), or any attempt on a DIFFERENT
     condition_id (a different 15-minute market), is never examined by
     this guard at all — it is scoped to the EXACT market+outcome pair
     that just failed, never a blanket pause on all entries.

A successful prior attempt (reconciled WITH a resulting position) is
explicitly never blocked here — that is risk.py's MAX_OPEN_POSITIONS'
job, unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import PolymarketPositionStore

# A reconciled-with-no-position terminal state -- see module docstring
# case 2. "submitted" is deliberately excluded here: a submitted order
# is only known to be a failure once fill_reconciled is True AND no
# position resulted (checked separately below), since "submitted" also
# covers the in-flight/not-yet-reconciled and the eventually-successful
# cases.
_TERMINAL_FAILURE_STATUSES = frozenset({"rejected", "failed", "expired"})


@dataclass(frozen=True)
class EntryRetryDecision:
    """Whether a NEW BUY for this exact (condition_id, outcome) may be
    submitted right now. `blocking_pending_order_id` is always set
    when `blocked` is True, naming the specific prior attempt
    responsible — useful for a human reviewing the decision log to
    find the exact record."""

    blocked: bool
    reason: str
    blocking_pending_order_id: str | None = None


def check_entry_retry_guard(
    pending_store: PolymarketPendingOrderStore,
    position_store: PolymarketPositionStore,
    *,
    condition_id: str,
    outcome: str,
    candidate_max_price: float,
    cooldown_seconds: float,
    min_price_change: float,
    now: datetime | None = None,
) -> EntryRetryDecision:
    """Pure (aside from the two read-only store loads) and side-effect
    free — callers (engine.py) decide what to log/return; this never
    mutates either store. Scoped to BUY orders only: a SELL (exit)
    pending record for the same condition_id is never examined here
    (exit_manager.py already owns its own, separate idempotency guard
    via OpenPosition.exit_pending_order_id)."""
    now = now or datetime.now(timezone.utc)

    same_market_buys = [
        p for p in pending_store.load()
        if p.order.condition_id == condition_id and p.order.outcome == outcome and p.order.side == "BUY"
    ]
    if not same_market_buys:
        return EntryRetryDecision(blocked=False, reason="No prior entry attempt for this market/outcome")

    latest = max(same_market_buys, key=lambda p: p.created_at)

    if latest.status == "awaiting_approval":
        return EntryRetryDecision(
            blocked=True,
            reason=(
                f"Prior entry attempt {latest.id} for {outcome} on {condition_id} is still "
                "awaiting human approval -- refusing a duplicate submission for the same setup"
            ),
            blocking_pending_order_id=latest.id,
        )

    if latest.status == "submitted" and not latest.fill_reconciled:
        return EntryRetryDecision(
            blocked=True,
            reason=(
                f"Prior entry attempt {latest.id} for {outcome} on {condition_id} was submitted but its "
                "fill status is not yet resolved (unknown, or not yet checked) -- refusing a duplicate "
                "submission until it reconciles"
            ),
            blocking_pending_order_id=latest.id,
        )

    if latest.status == "submitted" and position_store.get(latest.id) is not None:
        return EntryRetryDecision(blocked=False, reason="Prior entry attempt for this market/outcome already succeeded")

    if latest.status not in _TERMINAL_FAILURE_STATUSES and latest.status != "submitted":
        # Exhaustive over models.PENDING_STATUSES -- should be
        # unreachable, but fail OPEN (never blocking) rather than
        # silently locking out entries forever on an unrecognized
        # status this guard was never taught about.
        return EntryRetryDecision(blocked=False, reason=f"Prior attempt status {latest.status!r} not recognized as a failure -- not blocking")

    # A genuine failure: reconciled (or rejected/failed/expired
    # outright) with NO resulting position.
    reference_time = latest.decided_at or latest.created_at
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)
    elapsed = (now - reference_time).total_seconds()
    if elapsed >= cooldown_seconds:
        return EntryRetryDecision(
            blocked=False,
            reason=f"Prior failed attempt {latest.id} is {elapsed:.0f}s old -- cooldown ({cooldown_seconds:.0f}s) satisfied",
        )

    price_change = abs(candidate_max_price - latest.order.max_price)
    if price_change >= min_price_change:
        return EntryRetryDecision(
            blocked=False,
            reason=(
                f"Entry price moved ${price_change:.4f} since prior failed attempt {latest.id} "
                f"(>= ${min_price_change:.4f} threshold) -- materially changed setup, retry allowed"
            ),
        )

    return EntryRetryDecision(
        blocked=True,
        reason=(
            f"Prior entry attempt {latest.id} for {outcome} on {condition_id} failed {elapsed:.0f}s ago "
            f"(status={latest.status!r}) and price has only moved ${price_change:.4f} "
            f"(< ${min_price_change:.4f} threshold) -- not a materially changed setup; refusing an immediate retry"
        ),
        blocking_pending_order_id=latest.id,
    )
