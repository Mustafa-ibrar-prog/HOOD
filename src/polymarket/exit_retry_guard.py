"""Bounded retry/cooldown guard for automatic-EXIT (SELL) order
resubmission — the exit-side counterpart to entry_guard.py, closing a
related but distinct gap a live incident exposed:

    EXIT -> UNKNOWN -> EXPIRED -> EXIT -> UNKNOWN -> EXPIRED -> EXIT
    (repeats while the position keeps moving against the thesis)

exit_manager.py's OWN exit_pending_order_id guard (see positions.py's
docstring) already fully blocks a second exit while an existing one is
in flight or of UNKNOWN status — record_exit_fill() never clears it
for "unknown," exactly mirroring reconciliation.py's unknown-fill
handling on the entry side. That part was already correct and is
UNCHANGED.

The gap was one step further: once an exit order resolved to an
AUTHORITATIVE TERMINAL NON-FILL (expired, rejected, or failed — either
refused/timed out by the exchange, or blocked before ever reaching it),
record_exit_fill()/submit_dynamic_exit() immediately cleared
exit_pending_order_id with NO cooldown and NO check that anything
about the evidence had changed. If the same exit-worthy evidence was
still true next cycle — the overwhelmingly likely case, since BTC
momentum doesn't reverse direction every poll interval — the very next
check_and_execute_dynamic_exits() pass just submitted another exit,
which could ALSO expire, and so on: precisely the repeating cycle
observed live, during which the position's exposure to further adverse
price movement never actually decreased.

THE FIX: check_exit_retry_guard() below, consulted by
evaluate_dynamic_exit() ONLY once the current cycle's evidence has
ALREADY been judged exit-worthy on its own merits (see that function's
own call site) — this is a RATE LIMIT on resubmitting after a recent
failure, never a reason to hold a position whose evidence hasn't
turned, and never a replacement for exit_pending_order_id's own
unconditional UNKNOWN block above.

Persisted state (see positions.py's OpenPosition — no separate store
is needed here, unlike entry_guard.py's pending_store/position_store
pair, because a position already exists by the time an exit is ever
considered):

  - last_exit_attempt_at: when the most recent exit attempt for this
    position resolved to an authoritative, no-fill terminal outcome.
    None whenever there is nothing recently failed to rate-limit
    against.
  - last_exit_attempt_edge_points: the EdgeAssessment.btc_points
    reading (exit_manager.compute_edge_assessment) at the moment that
    failed attempt was submitted — the SAME continuous evidence score
    evaluate_dynamic_exit's own exit-worthy decision is already based
    on (see exit_manager.py's module docstring on why BTC evidence,
    not P&L, drives this system). Comparing it against the CURRENT
    btc_points answers "has the evidence materially changed" without
    re-deriving a second, separate notion of exit evidence.

A new exit is blocked only when BOTH of the following hold — either
the cooldown elapsing OR the evidence moving materially is enough to
permit an immediate retry, matching the requirement verbatim ("require
either a cooldown OR materially changed exit evidence before
retrying," never both):

  1. less than cooldown_seconds has elapsed since last_exit_attempt_at;
  2. the candidate btc_points has not moved by at least
     min_evidence_change (absolute value) from last_exit_attempt_edge_points.

A position with no prior failed attempt (last_exit_attempt_at is None)
is never blocked here at all — this guard is purely additive on top of
the existing exit-worthy decision, never a reason to hold by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.polymarket.positions import OpenPosition


@dataclass(frozen=True)
class ExitRetryDecision:
    """Whether a NEW exit order may be submitted for this position
    right now, given its own last-failed-attempt history. `blocked`
    is False whenever there is no prior failed attempt to rate-limit
    against at all."""

    blocked: bool
    reason: str


def check_exit_retry_guard(
    position: "OpenPosition",
    *,
    candidate_btc_points: float,
    cooldown_seconds: float,
    min_evidence_change: float,
    now: datetime | None = None,
) -> ExitRetryDecision:
    """Pure and side-effect free — callers (exit_manager.py) decide
    what to log/return; this never mutates the position. Only
    meaningful once the caller has ALREADY decided the position is
    exit-worthy on current evidence (see evaluate_dynamic_exit's own
    call site) — this never independently recommends holding a
    position whose evidence genuinely still supports an exit; it only
    rate-limits how soon a RECENTLY-FAILED attempt may be retried."""
    now = now or datetime.now(timezone.utc)

    if position.last_exit_attempt_at is None:
        return ExitRetryDecision(blocked=False, reason="No prior failed exit attempt for this position")

    reference_time = position.last_exit_attempt_at
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)
    elapsed = (now - reference_time).total_seconds()
    if elapsed >= cooldown_seconds:
        return ExitRetryDecision(
            blocked=False,
            reason=f"Prior failed exit attempt is {elapsed:.0f}s old -- cooldown ({cooldown_seconds:.0f}s) satisfied",
        )

    prior_points = position.last_exit_attempt_edge_points if position.last_exit_attempt_edge_points is not None else 0.0
    points_change = abs(candidate_btc_points - prior_points)
    if points_change >= min_evidence_change:
        return ExitRetryDecision(
            blocked=False,
            reason=(
                f"BTC evidence moved {points_change:.1f} points since the prior failed exit attempt "
                f"(>= {min_evidence_change:.1f} threshold) -- materially changed evidence, retry allowed"
            ),
        )

    return ExitRetryDecision(
        blocked=True,
        reason=(
            f"Prior exit attempt for {position.outcome} on {position.condition_id} failed {elapsed:.0f}s ago "
            f"with no fill, and BTC evidence has only moved {points_change:.1f} points "
            f"(< {min_evidence_change:.1f} threshold) -- not materially changed; refusing an immediate retry"
        ),
    )
