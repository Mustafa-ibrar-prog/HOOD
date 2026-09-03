"""Phase 21, Part 15 — dependence-aware resampling beyond Phase 7's
block/stationary bootstrap over a single series
(`src.research.return_series_bootstrap`, reused directly for the
time-block case). Option contract-day rows are dependent along a second
axis too: many rows share the same underlying symbol. This module adds
a SYMBOL-CLUSTER bootstrap -- resampling whole symbols (with
replacement), not individual rows -- so a confidence interval accounts
for "this panel really only has ~12 independent underlyings," not "9,044
independent rows."
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence

from src.research.ic import compute_ic_series, summarize_ic


@dataclass(frozen=True)
class SymbolClusterBootstrapReport:
    n_resamples: int
    seed: int
    n_symbols: int
    point_estimate: float | None
    confidence_level: float
    lower_bound: float | None
    upper_bound: float | None
    resampled_values: tuple[float, ...]

    def render(self) -> str:
        return (
            f"Symbol-cluster bootstrap (n_symbols={self.n_symbols}, n_resamples={self.n_resamples}): "
            f"point={self.point_estimate}  [{self.lower_bound}, {self.upper_bound}] ({self.confidence_level:.0%} CI)"
        )


def symbol_cluster_bootstrap_ic(
    panel_rows: Sequence[dict], *, feature_col: str, target_col: str, n_resamples: int = 1000, seed: int = 3001,
    confidence_level: float = 0.90, min_universe_size: int = 3,
) -> SymbolClusterBootstrapReport:
    """Resamples the SET OF SYMBOLS with replacement (not individual
    rows) `n_resamples` times; for each resample, keeps every row
    belonging to a chosen symbol (a symbol chosen twice contributes its
    rows twice) and recomputes the pooled cross-sectional IC. The
    resulting interval reflects symbol-level, not row-level, sample
    size -- the correct dependence unit here (Part 15's explicit
    instruction: 'do NOT treat every contract-day row as an independent
    observation')."""
    by_symbol: dict[str, list[dict]] = {}
    for row in panel_rows:
        by_symbol.setdefault(row["underlying_symbol"], []).append(row)
    symbols = list(by_symbol.keys())
    n_symbols = len(symbols)

    point_points = compute_ic_series(panel_rows, feature_col, target_col, min_universe_size=min_universe_size)
    point_estimate = summarize_ic(point_points, feature_name=feature_col, target_name=target_col).average_ic

    resampled: list[float] = []
    rng = random.Random(seed)
    for _ in range(n_resamples):
        chosen = [rng.choice(symbols) for _ in range(n_symbols)]
        resample_rows: list[dict] = []
        for sym in chosen:
            resample_rows.extend(by_symbol[sym])
        points = compute_ic_series(resample_rows, feature_col, target_col, min_universe_size=min_universe_size)
        ic = summarize_ic(points, feature_name=feature_col, target_name=target_col).average_ic
        if ic is not None:
            resampled.append(ic)

    if not resampled:
        return SymbolClusterBootstrapReport(
            n_resamples=n_resamples, seed=seed, n_symbols=n_symbols, point_estimate=point_estimate,
            confidence_level=confidence_level, lower_bound=None, upper_bound=None, resampled_values=(),
        )
    ordered = sorted(resampled)
    alpha = 1 - confidence_level
    lo_idx = int(len(ordered) * (alpha / 2))
    hi_idx = min(len(ordered) - 1, int(len(ordered) * (1 - alpha / 2)))
    return SymbolClusterBootstrapReport(
        n_resamples=n_resamples, seed=seed, n_symbols=n_symbols, point_estimate=point_estimate,
        confidence_level=confidence_level, lower_bound=ordered[lo_idx], upper_bound=ordered[hi_idx], resampled_values=tuple(resampled),
    )
