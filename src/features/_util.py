"""Private causal-windowing helpers shared by every feature module.

Everything here is deliberately pure Python (no numpy/pandas/scipy — this
project has zero third-party dependencies by design, see pyproject.toml)
and deliberately CAUSAL: `rolling_apply`/`shifted`/`pct_change` compute
output[i] using only series[0..i], never series[i+1:]. That's the
mechanical enforcement behind the no-future-data rule (see
src/features/base.py's module docstring) — every concrete Feature is built
out of these primitives specifically so an individual feature can't
accidentally reach forward without deliberately writing a hand-rolled loop
that ignores them.
"""

from __future__ import annotations

from typing import Callable, Sequence


def rolling_apply(series: Sequence[float], window: int, fn: Callable[[Sequence[float]], float]) -> list[float | None]:
    """output[i] = fn(series[i-window+1 : i+1]) once at least `window`
    values are available (i >= window - 1); None before that — "not enough
    history yet" is a real, honest answer, never a guessed early value."""
    if window < 1:
        raise ValueError("window must be >= 1")
    out: list[float | None] = []
    for i in range(len(series)):
        if i < window - 1:
            out.append(None)
        else:
            out.append(fn(series[i - window + 1 : i + 1]))
    return out


def shifted(series: Sequence[float], period: int) -> list[float | None]:
    """output[i] = series[i-period], or None if i < period."""
    if period < 0:
        raise ValueError("period must be >= 0")
    out: list[float | None] = []
    for i in range(len(series)):
        out.append(series[i - period] if i >= period else None)
    return out


def pct_change(series: Sequence[float], period: int) -> list[float | None]:
    """output[i] = (series[i] - series[i-period]) / series[i-period]."""
    base = shifted(series, period)
    out: list[float | None] = []
    for cur, b in zip(series, base):
        if b is None or b == 0:
            out.append(None)
        else:
            out.append((cur - b) / b)
    return out


def percentile_rank(values: Sequence[float], x: float) -> float:
    """Fraction of `values` <= x, in [0, 1]. `values` should already be the
    causal history available at the point of comparison (the caller's
    responsibility) — this function itself has no notion of time."""
    if not values:
        return 0.5
    return sum(1 for v in values if v <= x) / len(values)


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def stdev(xs: Sequence[float]) -> float:
    """Sample standard deviation (n-1 denominator). 0.0 for fewer than 2
    points — a single observation has no meaningful spread."""
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5
