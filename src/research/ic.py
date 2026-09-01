"""Information Coefficient analysis (Phase 4, section 10).

IC at one timestamp = the rank correlation between a feature's
cross-sectional ranking of the universe and the universe's SUBSEQUENT
realized-return ranking over the prediction horizon. This requires
MULTIPLE symbols observed at the same timestamp — it is a genuinely
different question from analyze_feature's pooled/time-series correlation
(src.research.analysis), which can run on a single symbol's history.

`rows` throughout this module is a "panel": rows from possibly several
symbols' ResearchDataset.rows (src.research.dataset), each carrying a
shared `timestamp` key plus the feature/target columns — exactly what you
get concatenating several symbols' ResearchDataset.rows together.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from src.research.analysis import mean, rank_values, spearman_correlation, stdev


@dataclass(frozen=True)
class ICPoint:
    timestamp: datetime
    ic: float | None  # None if fewer than min_universe_size symbols had both values at this timestamp
    sample_count: int


@dataclass(frozen=True)
class ICSummary:
    feature_name: str
    target_name: str
    points: tuple[ICPoint, ...]
    average_ic: float | None
    median_ic: float | None
    ic_stdev: float | None
    ic_information_ratio: float | None  # average_ic / ic_stdev — NOT the same as a Sharpe ratio; a persistence measure
    positive_ic_fraction: float | None  # fraction of non-None IC points with ic > 0

    def render(self) -> str:
        lines = [
            f"Feature: {self.feature_name}", f"Target: {self.target_name}",
            f"IC observations: {sum(1 for p in self.points if p.ic is not None)} / {len(self.points)} timestamps",
            f"Average IC: {self.average_ic}", f"Median IC: {self.median_ic}",
            f"IC stdev: {self.ic_stdev}", f"IC information ratio: {self.ic_information_ratio}",
            f"Positive-IC fraction: {self.positive_ic_fraction}",
        ]
        return "\n".join(lines)


def compute_ic_series(panel_rows: Sequence[dict], feature_col: str, target_col: str, *, min_universe_size: int = 3) -> list[ICPoint]:
    """One IC value per unique timestamp present in `panel_rows`. A
    timestamp with fewer than `min_universe_size` symbols carrying
    non-None feature AND target values produces ic=None — there's no
    meaningful cross-sectional ranking with 1-2 assets."""
    by_timestamp: dict[datetime, list[tuple[float, float]]] = defaultdict(list)
    for row in panel_rows:
        f, t = row.get(feature_col), row.get(target_col)
        if f is not None and t is not None:
            by_timestamp[row["timestamp"]].append((f, t))

    points: list[ICPoint] = []
    for ts in sorted(by_timestamp):
        pairs = by_timestamp[ts]
        if len(pairs) < min_universe_size:
            points.append(ICPoint(timestamp=ts, ic=None, sample_count=len(pairs)))
            continue
        features = [p[0] for p in pairs]
        targets = [p[1] for p in pairs]
        ic = spearman_correlation(features, targets)
        points.append(ICPoint(timestamp=ts, ic=ic, sample_count=len(pairs)))
    return points


def summarize_ic(points: Sequence[ICPoint], *, feature_name: str, target_name: str) -> ICSummary:
    values = [p.ic for p in points if p.ic is not None]
    if not values:
        return ICSummary(feature_name=feature_name, target_name=target_name, points=tuple(points), average_ic=None, median_ic=None, ic_stdev=None, ic_information_ratio=None, positive_ic_fraction=None)
    avg = mean(values)
    sd = stdev(values)
    return ICSummary(
        feature_name=feature_name, target_name=target_name, points=tuple(points),
        average_ic=avg, median_ic=sorted(values)[len(values) // 2], ic_stdev=sd,
        ic_information_ratio=(avg / sd) if sd > 0 else None,
        positive_ic_fraction=sum(1 for v in values if v > 0) / len(values),
    )


def ic_by_period(points: Sequence[ICPoint], *, period: str = "year") -> dict[str, ICSummary]:
    """`period`: "year" or "month" — buckets IC points by calendar
    period and summarizes each bucket separately (section 10's "IC by
    time period"). Regime-based bucketing is a separate, causal-labeling
    concern — see src.research.regime.ic_by_regime."""
    if period not in ("year", "month"):
        raise ValueError("period must be 'year' or 'month'")
    buckets: dict[str, list[ICPoint]] = defaultdict(list)
    for p in points:
        key = str(p.timestamp.year) if period == "year" else f"{p.timestamp.year}-{p.timestamp.month:02d}"
        buckets[key].append(p)
    return {key: summarize_ic(pts, feature_name="", target_name="") for key, pts in sorted(buckets.items())}
