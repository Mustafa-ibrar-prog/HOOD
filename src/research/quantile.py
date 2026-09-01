"""Cross-sectional quantile portfolio analysis (Phase 4, section 11).

At each timestamp, ranks the AVAILABLE UNIVERSE by a feature and buckets
it into `n_quantiles` groups, then aggregates each quantile's subsequent
returns across every timestamp. This is a genuinely different question
from src.research.analysis.analyze_feature's pooled time-series quantiles
(which quantile a single series of paired observations, not a per-instant
cross-section) — see src.research.ic's module docstring for the same
distinction applied to Information Coefficient.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from src.research.analysis import mean, stdev


@dataclass(frozen=True)
class CrossSectionalQuantileResult:
    quantile: int  # 1-indexed, 1 = lowest feature values
    mean_return: float
    median_return: float
    hit_rate: float
    sample_count: int  # total (symbol, timestamp) observations across all buckets of this quantile
    volatility: float


@dataclass(frozen=True)
class QuantilePortfolioReport:
    feature_name: str
    target_name: str
    quantiles: tuple[CrossSectionalQuantileResult, ...]
    spread_q5_minus_q1: float | None  # None if fewer than 2 quantiles produced
    is_monotonic: bool | None  # mean_return strictly non-decreasing from Q1 to Q_n
    timestamps_used: int

    def render(self) -> str:
        lines = [f"Feature: {self.feature_name}", f"Horizon target: {self.target_name}", ""]
        for q in self.quantiles:
            lines.append(f"Q{q.quantile}: n={q.sample_count} mean={q.mean_return:.5f} median={q.median_return:.5f} hit_rate={q.hit_rate:.2%} vol={q.volatility:.5f}")
        lines.append("")
        lines.append(f"Q{len(self.quantiles)}-Q1 spread: {self.spread_q5_minus_q1}")
        lines.append(f"Monotonic: {self.is_monotonic}")
        return "\n".join(lines)


def cross_sectional_quantile_returns(
    panel_rows: Sequence[dict], feature_col: str, target_col: str, *, n_quantiles: int = 5, min_universe_size: int = 3
) -> QuantilePortfolioReport:
    by_timestamp: dict[datetime, list[tuple[str, float, float]]] = defaultdict(list)
    for row in panel_rows:
        f, t = row.get(feature_col), row.get(target_col)
        if f is not None and t is not None:
            by_timestamp[row["timestamp"]].append((row.get("symbol", ""), f, t))

    bucket_returns: dict[int, list[float]] = defaultdict(list)
    timestamps_used = 0
    for ts, triples in by_timestamp.items():
        if len(triples) < min_universe_size:
            continue
        timestamps_used += 1
        ranked = sorted(triples, key=lambda triple: triple[1])
        n = len(ranked)
        for i, (_symbol, _feature, target) in enumerate(ranked):
            # Same "as-even-as-possible" bucketing as analyze_feature.
            bucket = min(n_quantiles - 1, (i * n_quantiles) // n)
            bucket_returns[bucket].append(target)

    quantiles: list[CrossSectionalQuantileResult] = []
    for q in range(n_quantiles):
        returns = bucket_returns.get(q, [])
        if not returns:
            continue
        quantiles.append(
            CrossSectionalQuantileResult(
                quantile=q + 1, mean_return=mean(returns), median_return=sorted(returns)[len(returns) // 2],
                hit_rate=sum(1 for r in returns if r > 0) / len(returns), sample_count=len(returns), volatility=stdev(returns),
            )
        )

    spread = None
    is_monotonic = None
    if len(quantiles) >= 2:
        spread = quantiles[-1].mean_return - quantiles[0].mean_return
        means = [q.mean_return for q in quantiles]
        is_monotonic = all(means[i] <= means[i + 1] for i in range(len(means) - 1))

    return QuantilePortfolioReport(
        feature_name=feature_col, target_name=target_col, quantiles=tuple(quantiles),
        spread_q5_minus_q1=spread, is_monotonic=is_monotonic, timestamps_used=timestamps_used,
    )
