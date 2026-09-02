"""Phase 11, Parts 14-15: tail-risk and drawdown-recovery statistics not
already covered by src.backtesting.metrics's PerformanceMetrics (which
already reports max/average drawdown, max-drawdown DURATION, and worst
day/week/month — see that module's own docstring). This module adds only
what's genuinely missing: historical VaR/CVaR at arbitrary confidence
levels, worst N-CONSECUTIVE-bar return (distinct from worst single
CALENDAR day/week/month), and drawdown RECOVERY time (bars from the
trough of the single worst drawdown back to a new equity high — distinct
from max_drawdown_duration_bars, which counts bars spent below ANY prior
peak, not specifically the recovery from the single worst trough).

Pure stdlib, same zero-third-party-dependency convention as every other
stats module in this package. Every function documents its own "limited
sample" caveat (Part 15's explicit "do not overstate tail estimates from
limited samples") rather than presenting a percentile-of-200-days VaR as
if it were a robust estimate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.backtesting.portfolio import EquityPoint


@dataclass(frozen=True)
class TailRiskReport:
    n_observations: int
    worst_1day_return: float | None
    worst_5day_return: float | None
    var_95: float | None  # historical VaR: the 5th percentile return (a LOSS is reported as a negative number)
    var_99: float | None
    cvar_95: float | None  # expected shortfall: mean of returns at-or-below the VaR_95 threshold
    cvar_99: float | None
    sample_size_caveat: str

    def render(self) -> str:
        def _f(x: float | None) -> str:
            return "None" if x is None else f"{x:.4%}"
        return (f"TailRisk(n={self.n_observations}): worst_1d={_f(self.worst_1day_return)} worst_5d={_f(self.worst_5day_return)} "
                f"VaR95={_f(self.var_95)} VaR99={_f(self.var_99)} CVaR95={_f(self.cvar_95)} CVaR99={_f(self.cvar_99)}")


def _percentile(sorted_values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile (p in [0,1]) of an ALREADY-SORTED sequence."""
    if not sorted_values:
        raise ValueError("empty sequence")
    idx = max(0, min(len(sorted_values) - 1, round(p * (len(sorted_values) - 1))))
    return sorted_values[idx]


def compute_tail_risk(period_returns: Sequence[float]) -> TailRiskReport:
    """`period_returns` should be the strategy's own per-bar (e.g. daily)
    equity returns, in chronological order. Worst-N-day figures use
    ROLLING, OVERLAPPING N-bar cumulative returns (product of (1+r)-1),
    not calendar week/month boundaries (contrast
    src.backtesting.metrics's worst_week_pct/worst_month_pct, which ARE
    calendar-boundary based — both are reported, deliberately measuring
    different things)."""
    n = len(period_returns)
    if n == 0:
        return TailRiskReport(0, None, None, None, None, None, None, "no return observations")

    worst_1day = min(period_returns)
    worst_5day = None
    if n >= 5:
        rolling_5 = []
        for i in range(n - 4):
            window = period_returns[i : i + 5]
            cum = 1.0
            for r in window:
                cum *= 1 + r
            rolling_5.append(cum - 1)
        worst_5day = min(rolling_5)

    sorted_returns = sorted(period_returns)
    var_95 = _percentile(sorted_returns, 0.05)
    var_99 = _percentile(sorted_returns, 0.01) if n >= 20 else None
    tail_95 = [r for r in sorted_returns if r <= var_95]
    tail_99 = [r for r in sorted_returns if r <= var_99] if var_99 is not None else None
    cvar_95 = sum(tail_95) / len(tail_95) if tail_95 else None
    cvar_99 = (sum(tail_99) / len(tail_99)) if tail_99 else None

    caveat = f"n={n} observations" + (" — VaR99/CVaR99 require >= 20 observations for even a coarse tail estimate" if n < 20 else "") + \
             (" — WARNING: any percentile-based tail estimate below ~100 observations is a rough, not a reliable, estimate" if n < 100 else "")

    return TailRiskReport(
        n_observations=n, worst_1day_return=worst_1day, worst_5day_return=worst_5day,
        var_95=var_95, var_99=var_99, cvar_95=cvar_95, cvar_99=cvar_99, sample_size_caveat=caveat,
    )


def recovery_time_bars(equity_curve: Sequence[EquityPoint]) -> int | None:
    """Bars from the TROUGH of the single WORST drawdown episode back to
    a NEW equity high (>= the pre-drawdown peak). Returns None if the
    strategy never had a drawdown, or if it never recovered by the end of
    the series (an unrecovered drawdown is real information, not an
    error — reported as None with the caller expected to also check
    max_drawdown_pct / whether the series just ended mid-drawdown)."""
    if not equity_curve:
        return None
    worst_idx = min(range(len(equity_curve)), key=lambda i: equity_curve[i].drawdown_pct)
    if equity_curve[worst_idx].drawdown_pct >= 0:
        return None  # never actually drew down
    peak_before_trough = equity_curve[worst_idx].equity - equity_curve[worst_idx].drawdown  # drawdown = equity - peak, so peak = equity - drawdown
    for offset, point in enumerate(equity_curve[worst_idx:]):
        if point.equity >= peak_before_trough:
            return offset
    return None  # never recovered within the available data
