"""Phase 9, Part 6: a Pearson-correlation companion to
src.research.ic.compute_ic_series (Phase 4, Spearman-only). Reuses
src.research.ic's own ICPoint/ICSummary dataclasses directly — this is
NOT a parallel schema, just a different correlation function plugged into
the identical per-timestamp cross-sectional structure.

Why this exists: Part 6 explicitly warns against relying solely on
Spearman IC after Phase 8's finding that a rank-based metric can behave
very differently from the underlying linear relationship. Reporting BOTH
here is a direct, structural response to that finding, not just a
docstring promise.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Sequence

from src.research.analysis import pearson_correlation
from src.research.ic import ICPoint, ICSummary, summarize_ic


def compute_pearson_ic_series(panel_rows: Sequence[dict], feature_col: str, target_col: str, *, min_universe_size: int = 3) -> list[ICPoint]:
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
        ic = pearson_correlation(features, targets)
        points.append(ICPoint(timestamp=ts, ic=ic, sample_count=len(pairs)))
    return points


def summarize_pearson_ic(points: Sequence[ICPoint], *, feature_name: str, target_name: str) -> ICSummary:
    """Thin wrapper — the summarization math (mean/median/stdev/IR/
    positive-fraction) is identical regardless of which correlation
    produced the points, so this reuses summarize_ic verbatim."""
    return summarize_ic(points, feature_name=feature_name, target_name=target_name)
