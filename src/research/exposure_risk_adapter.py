"""Phase 11: a risk adapter purpose-built for CONTINUOUS-EXPOSURE
strategies — a new, additive sibling to src.backtesting.risk_adapter.
BacktestRiskAdapter (Phase 3, completely unmodified), not a replacement
for it. Still genuinely reuses src.risk.manager.RiskManager unmodified —
only WHICH of its checks apply is different.

WHY THIS EXISTS (found via a smoke test before any real backtest ran):
BacktestRiskAdapter.review() runs check_duplicate_position,
check_cooldown, and check_no_size_increase_after_loss — all correct and
important for a strategy that ENTERS a fresh, discrete position on a
signal and must not silently pyramid into it or re-enter right after a
stop-out. A volatility-CONDITIONED-EXPOSURE strategy is structurally
different: "increase SPY exposure from 60% back to 90%" is not opening a
duplicate position or re-entering after an exit — it is routine
REBALANCING of a single, continuously-held, already-intended allocation.
Running the unmodified BacktestRiskAdapter against this strategy shape
silently RATCHETS exposure downward forever (every reduce succeeds,
since exits are never blocked; every subsequent increase gets rejected
by check_duplicate_position, since a position is already held) — a real
bug this smoke test caught, not a hypothetical concern.

What THIS adapter still enforces (Part 6's own preregistered exposure
bounds are enforced upstream, by exposure_mechanisms.py's clamping — this
adapter is a second, independent layer, not the only one):
  - check_position_size (position size limit)
  - check_daily_loss (daily loss circuit breaker)
  - check_extended_move (extended single-bar move circuit breaker)
What it deliberately SKIPS, and why:
  - check_duplicate_position: adding to an existing, intentionally-held
    allocation is not "duplicate" — it's the entire point of exposure
    rebalancing.
  - check_cooldown / check_no_size_increase_after_loss: both exist to
    prevent re-entering right after an exit/loss for a DISCRETE trade;
    a continuously-held allocation was never "exited," so there is
    nothing to cool down from.
"""

from __future__ import annotations

from src.backtesting.risk_adapter import RiskReview
from src.risk.manager import RiskCheckResult, RiskManager


class ExposureRiskAdapter:
    def __init__(self, risk_manager: RiskManager):
        self._rm = risk_manager

    def review(
        self, *, symbol: str, proposed_quantity: int, reference_price: float,
        daily_pnl_usd: float, underlying_move_pct: float = 0.0, **_ignored,
    ) -> RiskReview:
        if proposed_quantity <= 0:
            return RiskReview("REJECTED", 0, "proposed_quantity must be > 0", ())

        checks: list[RiskCheckResult] = []
        quantity = proposed_quantity
        modified = False

        proposed_size_usd = quantity * reference_price
        size_check = self._rm.check_position_size(proposed_size_usd)
        if not size_check.passed:
            max_affordable_qty = int(self._rm.limits.max_position_size_usd // reference_price) if reference_price > 0 else 0
            if max_affordable_qty <= 0:
                checks.append(size_check)
                return RiskReview("REJECTED", 0, size_check.message, tuple(checks))
            quantity = max_affordable_qty
            proposed_size_usd = quantity * reference_price
            modified = True
            size_check = self._rm.check_position_size(proposed_size_usd)
        checks.append(size_check)
        checks.append(self._rm.check_daily_loss(daily_pnl_usd))
        checks.append(self._rm.check_extended_move(underlying_move_pct))

        blocking = [c for c in checks if not c.passed]
        if blocking:
            return RiskReview("REJECTED", 0, "; ".join(c.message for c in blocking), tuple(checks))

        decision = "MODIFIED" if modified else "APPROVED"
        reason = f"Reduced from {proposed_quantity} to {quantity} shares to fit MAX_POSITION_SIZE_USD" if modified else "All risk checks passed"
        return RiskReview(decision, quantity, reason, tuple(checks))
