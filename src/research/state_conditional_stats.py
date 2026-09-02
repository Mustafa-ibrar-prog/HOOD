"""Phase 10, Parts 12-14: distributional statistics of a target column,
bucketed by a discrete state feature (e.g. volatility_regime) — a NEW,
generic module. Distinct from src.research.ic (cross-sectional rank/
linear correlation) and src.research.quantile (continuous-feature
quantile portfolios): this answers "what does the target's own
DISTRIBUTION look like conditional on being in state X," which is what
Part 12 ("mean/median/Sharpe/downside deviation/win rate by volatility
state") actually asks for, not a correlation coefficient.

The "Sharpe" reported here is NOT an annualized time-series Sharpe (Phase
3's compute_performance_metrics, which operates on an equity curve, is
the wrong tool for a scattered cross-sectional/panel sample) — it's the
simple mean/stdev ratio of the per-row target values falling in that
state, explicitly labeled as such.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.research.analysis import mean, stdev


@dataclass(frozen=True)
class StateBucketStats:
    state: str
    sample_count: int
    mean_value: float | None
    median_value: float | None
    stdev_value: float | None
    sharpe_like: float | None  # mean/stdev of the per-row target values in this state, NOT annualized
    downside_deviation: float | None  # stdev of the subset of values < 0
    win_rate: float | None  # fraction of values > 0
    mean_absolute_value: float | None


def bucket_stats_by_state(panel_rows: Sequence[dict], state_col: str, target_col: str, *, min_count: int = 5) -> dict[str, StateBucketStats]:
    by_state: dict[str, list[float]] = {}
    for row in panel_rows:
        state, value = row.get(state_col), row.get(target_col)
        if state is None or value is None:
            continue
        by_state.setdefault(str(state), []).append(value)

    out: dict[str, StateBucketStats] = {}
    for state, values in by_state.items():
        n = len(values)
        if n < min_count:
            out[state] = StateBucketStats(state=state, sample_count=n, mean_value=None, median_value=None, stdev_value=None, sharpe_like=None, downside_deviation=None, win_rate=None, mean_absolute_value=None)
            continue
        sd = stdev(values)
        downside = [v for v in values if v < 0]
        out[state] = StateBucketStats(
            state=state, sample_count=n, mean_value=mean(values), median_value=_median(values), stdev_value=sd,
            sharpe_like=(mean(values) / sd if sd > 0 else None),
            downside_deviation=(stdev(downside) if len(downside) >= 2 else None),
            win_rate=sum(1 for v in values if v > 0) / n,
            mean_absolute_value=mean([abs(v) for v in values]),
        )
    return out


def _median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0
