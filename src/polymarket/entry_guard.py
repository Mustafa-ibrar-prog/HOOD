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

SECOND LIVE INCIDENT, FIXED HERE: the FIRST version of this guard
explicitly let a new entry through once a prior attempt on the exact
same (condition_id, outcome) had already succeeded — on the reasoning
that risk.py's MAX_OPEN_POSITIONS would be the backstop against
duplicating it. That reasoning was wrong: MAX_OPEN_POSITIONS counts
positions GLOBALLY (across every market), never per-market — with
POLYMARKET_MAX_OPEN_POSITIONS=2, a market that already had one open
position still had "room" under the cap, so a second entry for the
IDENTICAL (condition_id, outcome) sailed straight through:

    order D0B9C7Y7JZ8H -> unknown -> (later) position_opened 7 @ $0.69
    order D0B9RW0CJZ8H -> unknown -> (later) position_opened 7 @ $0.63
    (same condition_id "btc-updown-15m-2026-10-09-1900z", same outcome "YES")

The exact race: cycle N submits order #1 (pending P1, status=submitted,
fill_reconciled=False — correctly blocks a retry at this point). Some
LATER point — reconcile_pending_orders()'s sweep at the top of a
cycle, possibly the very next one — resolves P1 as FILLED, creating
the position and setting P1.fill_reconciled=True. The STRATEGY, with
market momentum unchanged, proposes the SAME entry again THAT SAME
cycle (reconcile_pending_orders() runs before the entry evaluation
below it in run_cycle()). risk.py's MAX_OPEN_POSITIONS passed (1 < 2).
This guard's old logic saw P1 as "status=submitted AND a position
exists for P1.id" and read that as "already succeeded, not my
problem" — never checking whether a position for THIS EXACT
(condition_id, outcome) already existed, regardless of which pending
record created it. Order #2 (P2) went out, filled too: a real,
duplicate, same-side position on the same binary market.

THE FIX: an unconditional, FIRST check against the POSITION LEDGER
itself (position_store), independent of pending_store entirely —
"only ONE live entry attempt (pending OR already-filled) may exist
for this exact (condition_id, outcome) at a time." If ANY OpenPosition
already exists for this (condition_id, outcome), a new entry is ALWAYS
blocked — no cooldown, no price-change escape (a price move is never
grounds to open a SECOND position on a market you already hold; that
is not "a materially different setup," it is a duplicate by
definition). This is checked BEFORE the pending-order examination
below, so it protects both LIVE (the race above) and PAPER mode
(PaperPolymarketGateway never touches pending_store at all, so the
pending-order checks below were ALWAYS a complete no-op for paper
fills — this position-ledger check is what actually protects paper
mode too).

Beyond that unconditional check, two more cases, matched to the user's
own description ("unresolved OR recently failed"):

  1. UNRESOLVED — the most recent PENDING entry attempt for this exact
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
     Blocks for cooldown_seconds UNLESS the entry price has moved by
     at least min_price_change since that attempt — "require a
     materially changed entry condition before retrying."

A different outcome (YES vs NO), or any attempt on a DIFFERENT
condition_id (a different 15-minute market), is never examined by
this guard at all — it is scoped to the EXACT market+outcome pair,
never a blanket pause on all entries.
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

    # Unconditional, ground-truth check against the POSITION LEDGER --
    # see this module's own docstring on the second live incident this
    # fixed. Never bypassed by cooldown or price-change: a second
    # position on a market/outcome you already hold is never "a
    # materially different setup."
    existing_positions = [
        p for p in position_store.load() if p.condition_id == condition_id and p.outcome == outcome
    ]
    if existing_positions:
        existing = existing_positions[0]
        return EntryRetryDecision(
            blocked=True,
            reason=(
                f"An open position already exists for {outcome} on {condition_id} "
                f"({existing.filled_shares:.4f} shares @ ${existing.avg_fill_price:.4f}, client_order_id="
                f"{existing.client_order_id!r}) -- refusing a duplicate entry regardless of MAX_OPEN_POSITIONS"
            ),
            blocking_pending_order_id=existing.client_order_id,
        )

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

    # A "submitted" attempt reaching this point is reconciled
    # (fill_reconciled=True, from the check above) -- and the
    # unconditional position-ledger check at the top already proved no
    # position exists for this condition_id/outcome at all, so this is
    # necessarily a reconciled-but-not-filled outcome: falls through to
    # the same failure/cooldown logic as an explicit rejected/expired/
    # failed status below.
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
