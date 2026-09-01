"""Shared statistical primitives for Phase 7's validation layer — pure
stdlib (`math` only), same zero-third-party-dependency convention as
src/research/analysis.py.

`normal_cdf`/`two_tailed_p_value_from_z` use the standard normal
distribution (via `math.erf`), which is only an approximation of the
t-distribution — accurate for reasonably large sample sizes (rule of
thumb: n >= ~30) and INCREASINGLY WRONG for small n, where a true
t-distribution has fatter tails. This module never pretends otherwise:
every p-value function here documents that it is a NORMAL APPROXIMATION,
not an exact t-test, and callers with small samples should treat the
result as directional, not exact.
"""

from __future__ import annotations

import math
from typing import Sequence

from src.research.analysis import mean, stdev


def normal_cdf(z: float) -> float:
    """Standard normal CDF via the error function — exact for a true
    normal distribution, no external dependency needed."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def two_tailed_p_value_from_z(z: float) -> float:
    """P(|Z| >= |z|) under a standard normal — a NORMAL APPROXIMATION to
    a two-tailed test. For small samples this understates how extreme a
    given t-statistic really needs to be (t-distributions have fatter
    tails than normal); treat as approximate, not exact, below n≈30."""
    return 2.0 * (1.0 - normal_cdf(abs(z)))


def t_statistic(values: Sequence[float], *, null_mean: float = 0.0) -> float | None:
    """One-sample t-statistic for testing whether `values`' mean differs
    from `null_mean`. None if fewer than 2 values or zero variance."""
    n = len(values)
    if n < 2:
        return None
    sd = stdev(values)
    if sd == 0:
        return None
    return (mean(values) - null_mean) / (sd / math.sqrt(n))


def t_test_p_value(values: Sequence[float], *, null_mean: float = 0.0) -> float | None:
    """Two-tailed p-value for a one-sample t-test, via the normal
    approximation documented above. None if t_statistic is undefined."""
    t = t_statistic(values, null_mean=null_mean)
    if t is None:
        return None
    return two_tailed_p_value_from_z(t)


def sharpe_ratio_from_returns(returns: Sequence[float], *, periods_per_year: float = 252.0) -> float | None:
    """A simple annualized Sharpe from a return series — 0% risk-free
    rate, not netted out (same convention as src/backtesting/metrics.py)."""
    if len(returns) < 2:
        return None
    sd = stdev(returns)
    if sd == 0:
        return None
    return (mean(returns) / sd) * math.sqrt(periods_per_year)
