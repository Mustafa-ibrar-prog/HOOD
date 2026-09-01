"""Phase 8, Part 15: lag-autocorrelation — a small, generic utility for
the shift-placebo/alignment investigation. Reuses
src.research.analysis.pearson_correlation rather than reimplementing
correlation; adds nothing but the lagging itself.
"""

from __future__ import annotations

from typing import Sequence

from src.research.analysis import pearson_correlation


def lag_autocorrelation(values: Sequence[float | None], lag: int) -> float | None:
    """Pearson correlation between values[t] and values[t+lag], dropping
    any pair where either side is None. None if fewer than 2 valid pairs
    remain or `lag` is not a positive integer smaller than the series."""
    if lag < 1 or lag >= len(values):
        return None
    pairs = [(values[i], values[i + lag]) for i in range(len(values) - lag) if values[i] is not None and values[i + lag] is not None]
    if len(pairs) < 2:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    return pearson_correlation(xs, ys)  # type: ignore[arg-type]


def autocorrelation_profile(values: Sequence[float | None], lags: Sequence[int]) -> dict[int, float | None]:
    return {lag: lag_autocorrelation(values, lag) for lag in lags}
