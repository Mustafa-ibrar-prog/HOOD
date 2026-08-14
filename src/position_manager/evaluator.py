"""The position-management framework's decision core.

This is where "should we HOLD, EXIT, TARGET_EXIT, or STOP_EXIT this open
position?" gets decided. It is deliberately evidence-driven rather than
price-driven:

  - Reaching the profit target does NOT automatically exit. If momentum
    evidence still shows strengthening, the evaluator recommends HOLD past
    the target ("do not require the system to wait for the $20 target" —
    read literally in both directions: don't force a wait, and don't force
    a stop there either, if the evidence says the move has legs).
  - Falling short of the profit target does NOT prevent an early exit. If
    the evidence shows the move has weakened or peaked, the evaluator
    recommends EXIT before the target is ever reached.
  - A mere pause — flat price action with no corroborating signals — is
    never enough on its own. That distinction lives in
    strategy/evidence.py's WEAKENING_THRESHOLD (requires multiple
    corroborating signals, not one soft blip).
  - Hard stops (max loss, thesis invalidation, expiration risk) always take
    priority over momentum reasoning — those are risk controls, not
    opinions.

DYNAMIC / TRAILING EXIT (deterministic, price-only — independent of the
momentum-evidence engine above): once a position's unrealized gain reaches
EvaluatorConfig.trailing_arm_fraction of the distance from entry to its
profit target, trailing protection "arms". From that point on, if price
gives back EvaluatorConfig.trailing_giveback_fraction of the gain made from
entry to the position's peak-price-so-far, the position exits immediately
— it does not wait for the original target, and it does not require any
momentum-evidence signal to fire. Example, straight from the requirement:
entry $0.95, target $1.15 (a $0.20 range). With the default 0.5/0.3
fractions: price reaching $1.05 arms trailing (50% of the way to target);
if price then falls back to $1.02 (giving back 30% of the $0.10 gained
from entry to that $1.05 peak), the position exits there rather than
waiting for $1.15. See _evaluate_trailing_exit() below.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.position_manager.models import OpenPosition
from src.strategy.decision import Decision, DecisionResult
from src.strategy.evidence import MomentumEvidence, MomentumState, evaluate_momentum


@dataclass(frozen=True)
class PositionSnapshot:
    """Everything needed to evaluate one open position on one cycle."""

    position: OpenPosition
    option_price: float  # current mid/last price per contract
    momentum: MomentumEvidence
    minutes_to_expiration: float
    # Highest option price observed for this position across every cycle
    # so far, INCLUDING this one (i.e. already max()'d with option_price by
    # the caller — see position_manager/peak_tracker.py). Defaults to
    # option_price when the caller has no cross-cycle memory, which safely
    # degrades the trailing-exit check to a same-cycle no-op rather than
    # crashing.
    peak_price: float | None = None
    thesis_invalidated: bool = False
    thesis_invalidation_reason: str = ""

    def __post_init__(self) -> None:
        if self.peak_price is None:
            object.__setattr__(self, "peak_price", self.option_price)


@dataclass(frozen=True)
class EvaluatorConfig:
    # Minimum corroborating weakening signals required before an early EXIT
    # is recommended on a profitable-but-not-yet-target position. This is
    # already enforced inside evaluate_momentum's WEAKENING_THRESHOLD; this
    # is a second, position-level gate so a position with a barely-WEAKENING
    # read (few signals) doesn't get exited on a technicality.
    min_weakening_signals_for_exit: int = 2
    # Inside this many minutes of expiration-day close, expiration risk
    # rules override ordinary momentum-based holding.
    expiration_buffer_minutes: float = 30.0
    # Dynamic/trailing exit — see module docstring. Both come from
    # Settings.trailing_arm_fraction / trailing_giveback_fraction in normal
    # use (see orchestrator.py); the defaults here match Settings' own
    # defaults so a bare EvaluatorConfig() is still sensible in tests.
    trailing_arm_fraction: float = 0.5
    trailing_giveback_fraction: float = 0.3


class PositionEvaluator:
    def __init__(self, config: EvaluatorConfig | None = None):
        self.config = config or EvaluatorConfig()

    def evaluate(self, snapshot: PositionSnapshot) -> DecisionResult:
        position = snapshot.position
        pnl_usd = position.unrealized_pnl_usd(snapshot.option_price)
        pnl_pct = position.unrealized_pnl_pct(snapshot.option_price)
        assessment = evaluate_momentum(snapshot.momentum)

        base_evidence = {
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "option_price": snapshot.option_price,
            "entry_price": position.entry_price,
            "momentum_state": assessment.state.value,
            "momentum_signals": list(assessment.signals),
            "weakening_score": assessment.weakening_score,
            "strengthening_score": assessment.strengthening_score,
            "minutes_to_expiration": snapshot.minutes_to_expiration,
        }

        # --- 1. Thesis invalidated: highest-priority hard stop -------------------
        if snapshot.thesis_invalidated:
            return DecisionResult(
                decision=Decision.STOP_EXIT,
                reason=f"Original trade thesis invalidated: {snapshot.thesis_invalidation_reason}",
                confidence=1.0,
                evidence=base_evidence,
            )

        # --- 2. Hard stop-loss: never overridden by momentum reasoning -----------
        if pnl_usd <= -abs(position.stop_loss_usd):
            return DecisionResult(
                decision=Decision.STOP_EXIT,
                reason=(
                    f"Stop-loss breached: unrealized P&L ${pnl_usd:.2f} at/below "
                    f"-${position.stop_loss_usd:.2f}"
                ),
                confidence=1.0,
                evidence=base_evidence,
            )

        # --- 3. Expiration risk -----------------------------------------------------
        if snapshot.minutes_to_expiration <= self.config.expiration_buffer_minutes:
            if pnl_usd > 0:
                return DecisionResult(
                    decision=Decision.TARGET_EXIT,
                    reason=(
                        f"Only {snapshot.minutes_to_expiration:.0f} min to expiration; "
                        f"closing a profitable (${pnl_usd:.2f}) position ahead of "
                        "time-decay/pin risk rather than holding into the close"
                    ),
                    confidence=0.9,
                    evidence=base_evidence,
                )
            return DecisionResult(
                decision=Decision.STOP_EXIT,
                reason=(
                    f"Only {snapshot.minutes_to_expiration:.0f} min to expiration and "
                    f"position is unprofitable (${pnl_usd:.2f}); closing to avoid "
                    "expiring worthless"
                ),
                confidence=0.9,
                evidence=base_evidence,
            )

        # --- 4. Dynamic/trailing exit: deterministic, price-only ---------------------
        # Independent of momentum evidence on purpose (runs even when momentum
        # data is INSUFFICIENT_DATA below) — see module docstring for the
        # worked example. A pure price-structure signal, not an opinion.
        trailing_triggered, trailing_reason = _evaluate_trailing_exit(position, snapshot, self.config)
        if trailing_triggered:
            return DecisionResult(
                decision=Decision.EXIT,
                reason=trailing_reason,
                confidence=0.85,
                evidence={**base_evidence, "peak_price": snapshot.peak_price},
            )

        # --- 5. Insufficient evidence: fail safe, never guess ------------------------
        if assessment.state is MomentumState.INSUFFICIENT_DATA:
            return DecisionResult(
                decision=Decision.HOLD,
                reason="Insufficient evidence this cycle to justify any exit; maintaining position",
                confidence=0.3,
                evidence=base_evidence,
            )

        # --- 6. Profitable position, momentum-driven early exit ----------------------
        # This is the core "don't wait for the target, but don't exit on a
        # pause either" rule: act on WEAKENING/REVERSING with enough
        # corroborating signals, regardless of whether the target was hit.
        if pnl_usd > 0 and assessment.state in (MomentumState.WEAKENING, MomentumState.REVERSING):
            if len(assessment.signals) >= self.config.min_weakening_signals_for_exit:
                return DecisionResult(
                    decision=Decision.EXIT,
                    reason=(
                        f"Profitable (${pnl_usd:.2f}) but evidence shows the move has "
                        f"{assessment.state.value.lower()} ({', '.join(assessment.signals)}); "
                        "exiting early rather than waiting for the profit target or a reversal"
                    ),
                    confidence=min(0.95, 0.5 + 0.1 * len(assessment.signals)),
                    evidence=base_evidence,
                )

        # --- 7. Profit target reached ------------------------------------------------
        if pnl_usd >= position.profit_target_usd:
            if assessment.state is MomentumState.STRENGTHENING:
                return DecisionResult(
                    decision=Decision.HOLD,
                    reason=(
                        f"Profit target (${position.profit_target_usd:.2f}) reached but momentum "
                        f"is strengthening ({', '.join(assessment.signals)}); letting the position "
                        "run rather than capping the winner"
                    ),
                    confidence=0.7,
                    evidence=base_evidence,
                )
            return DecisionResult(
                decision=Decision.TARGET_EXIT,
                reason=(
                    f"Profit target (${position.profit_target_usd:.2f}) reached; momentum is "
                    f"{assessment.state.value.lower()}, not confirming further continuation — locking in the gain"
                ),
                confidence=0.75,
                evidence=base_evidence,
            )

        # --- 8. Default: hold ----------------------------------------------------------
        hold_reason = (
            f"No exit condition met (P&L ${pnl_usd:.2f}, momentum {assessment.state.value.lower()}); "
            "maintaining position"
        )
        return DecisionResult(decision=Decision.HOLD, reason=hold_reason, confidence=0.6, evidence=base_evidence)


def _target_price(position: OpenPosition) -> float:
    """Per-contract price that corresponds to position.profit_target_usd
    (a whole-position dollar figure) — needed because the trailing engine
    reasons in price terms, the same terms the requirement's example used
    ($0.95 entry, $1.15 target)."""
    per_contract_target_gain = position.profit_target_usd / (position.quantity * position.contract_multiplier)
    return position.entry_price + per_contract_target_gain


def _evaluate_trailing_exit(
    position: OpenPosition, snapshot: PositionSnapshot, config: EvaluatorConfig
) -> tuple[bool, str]:
    """Deterministic, price-only dynamic exit. See module docstring for the
    worked example. Returns (should_exit, reason); reason is only
    meaningful when should_exit is True."""
    peak_price = snapshot.peak_price if snapshot.peak_price is not None else snapshot.option_price
    gain_to_peak = peak_price - position.entry_price
    if gain_to_peak <= 0:
        return False, ""  # never been profitable — nothing to trail

    target_price = _target_price(position)
    target_range = target_price - position.entry_price
    if target_range <= 0:
        return False, ""  # degenerate config; nothing sensible to arm against

    arm_price = position.entry_price + config.trailing_arm_fraction * target_range
    if peak_price < arm_price:
        return False, ""  # not armed yet — hasn't gained enough to trail

    trigger_price = peak_price - config.trailing_giveback_fraction * gain_to_peak
    if snapshot.option_price <= trigger_price:
        giveback_usd = (peak_price - snapshot.option_price) * position.quantity * position.contract_multiplier
        return True, (
            f"Trailing exit: price peaked at ${peak_price:.2f} (armed at ${arm_price:.2f}, "
            f"{config.trailing_arm_fraction:.0%} of the way to the ${target_price:.2f} target) and has "
            f"since given back ${giveback_usd:.2f} to ${snapshot.option_price:.2f} — "
            f"{config.trailing_giveback_fraction:.0%} of the peak gain — exiting now rather than "
            "waiting for the original target or a reversal"
        )
    return False, ""
