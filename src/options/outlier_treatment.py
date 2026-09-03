"""Phase 21, Part 10 — mandatory outlier falsification: winsorization,
top/bottom-percentile removal, and attribution of how much of a pooled
effect a handful of extreme observations contribute.

Phase 20 surfaced a real, disclosed data characteristic: raw percentage
option returns are dominated by a small number of genuine, extreme
near-zero-basis price moves. This module makes checking that mechanical
rather than something re-derived ad hoc in every script that needs it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


def winsorize(values: Sequence[float], *, fraction: float) -> list[float]:
    """Caps the top and bottom `fraction` of values at their respective
    percentile boundary (e.g. fraction=0.01 caps the top/bottom 1%) --
    does not remove observations, only clips their magnitude. `fraction`
    must be in [0, 0.5)."""
    if not (0 <= fraction < 0.5):
        raise ValueError(f"fraction must be in [0, 0.5), got {fraction}")
    if not values:
        return []
    ordered = sorted(values)
    n = len(ordered)
    lo_idx = int(n * fraction)
    hi_idx = n - 1 - int(n * fraction)
    lo_idx = max(0, min(lo_idx, n - 1))
    hi_idx = max(0, min(hi_idx, n - 1))
    lo_bound, hi_bound = ordered[lo_idx], ordered[hi_idx]
    return [min(max(v, lo_bound), hi_bound) for v in values]


def remove_top_percent(values: Sequence[float], *, fraction: float, side: str) -> list[float]:
    """Removes (not clips) the top `fraction` of POSITIVE values
    (side='positive') or the most-negative `fraction` of NEGATIVE values
    (side='negative') -- Part 10's items 2/3 ('remove top 1% positive
    observations' / 'remove top 1% negative observations'), distinct
    from winsorizing both tails at once."""
    if side not in ("positive", "negative"):
        raise ValueError(f"side must be 'positive' or 'negative', got {side!r}")
    if not values:
        return []
    n_to_remove = int(len(values) * fraction)
    if n_to_remove == 0:
        return list(values)
    if side == "positive":
        ordered = sorted(range(len(values)), key=lambda i: values[i], reverse=True)
    else:
        ordered = sorted(range(len(values)), key=lambda i: values[i])
    remove_indices = set(ordered[:n_to_remove])
    return [v for i, v in enumerate(values) if i not in remove_indices]


@dataclass(frozen=True)
class TopObservation:
    index: int  # position within the original values sequence
    value: float


def top_observations(values: Sequence[float], *, n: int, by: str = "absolute") -> tuple[TopObservation, ...]:
    """The `n` most extreme observations. `by='absolute'` ranks by
    |value| (Part 10's 'top 5/10 observations'); `by='positive'`/
    `'negative'` rank by signed value in that direction."""
    if by not in ("absolute", "positive", "negative"):
        raise ValueError(f"by must be 'absolute', 'positive', or 'negative', got {by!r}")
    key = {"absolute": lambda v: abs(v), "positive": lambda v: v, "negative": lambda v: -v}[by]
    ordered = sorted(range(len(values)), key=lambda i: key(values[i]), reverse=True)
    return tuple(TopObservation(index=i, value=values[i]) for i in ordered[:n])


@dataclass(frozen=True)
class OutlierAttribution:
    total_sum: float
    top_1pct_sum: float
    top_5pct_sum: float
    top_10pct_sum: float

    @property
    def top_1pct_share(self) -> float | None:
        return None if self.total_sum == 0 else self.top_1pct_sum / self.total_sum

    @property
    def top_5pct_share(self) -> float | None:
        return None if self.total_sum == 0 else self.top_5pct_sum / self.total_sum

    @property
    def top_10pct_share(self) -> float | None:
        return None if self.total_sum == 0 else self.top_10pct_sum / self.total_sum


def compute_outlier_attribution(values: Sequence[float]) -> OutlierAttribution:
    """What fraction of the pooled SUM (e.g. of returns feeding a mean)
    is contributed by the most extreme (by absolute value) 1%/5%/10% of
    observations -- Part 10's explicit attribution requirement."""
    n = len(values)
    total = sum(values)
    if n == 0:
        return OutlierAttribution(total_sum=0.0, top_1pct_sum=0.0, top_5pct_sum=0.0, top_10pct_sum=0.0)
    ranked = sorted(values, key=lambda v: abs(v), reverse=True)
    n1 = max(1, int(n * 0.01)) if n >= 100 else max(0, int(n * 0.01))
    n5 = max(1, int(n * 0.05)) if n >= 20 else max(0, int(n * 0.05))
    n10 = max(1, int(n * 0.10)) if n >= 10 else max(0, int(n * 0.10))
    return OutlierAttribution(
        total_sum=total, top_1pct_sum=sum(ranked[:n1]), top_5pct_sum=sum(ranked[:n5]), top_10pct_sum=sum(ranked[:n10]),
    )
