"""Predictive feature analysis: does a feature have any measurable
relationship with future returns?

RESEARCH ONLY. Nothing here (or anywhere downstream) automatically turns a
statistically-interesting feature into a trading strategy, a risk
parameter, or a live signal — that decision stays explicitly human, in a
later phase.

Pure stdlib (no numpy/pandas/scipy — this project has zero third-party
dependencies by design; see pyproject.toml).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class QuantileResult:
    quantile: int  # 1-indexed, 1 = lowest feature values
    mean_future_return: float
    median_future_return: float
    hit_rate: float  # fraction of samples in this quantile with a positive future return
    sample_count: int
    volatility: float  # sample stdev of future returns in this quantile


@dataclass(frozen=True)
class FeatureAnalysisResult:
    feature_name: str
    target_name: str
    sample_count: int
    pearson_correlation: float | None
    spearman_correlation: float | None
    quantiles: tuple[QuantileResult, ...]
    significance_note: str

    def render(self) -> str:
        lines = [
            f"Feature: {self.feature_name}",
            f"Target: {self.target_name}",
            f"Samples: {self.sample_count}",
            f"Pearson correlation: {self.pearson_correlation}",
            f"Spearman (rank) correlation: {self.spearman_correlation}",
            "",
        ]
        for q in self.quantiles:
            lines.append(
                f"Q{q.quantile}: n={q.sample_count} mean={q.mean_future_return:.5f} "
                f"median={q.median_future_return:.5f} hit_rate={q.hit_rate:.2%} vol={q.volatility:.5f}"
            )
        lines.append("")
        lines.append(self.significance_note)
        return "\n".join(lines)


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def stdev(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def pearson_correlation(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = mean(xs), mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return cov / (sx * sy)


def rank_values(xs: Sequence[float]) -> list[float]:
    """Average rank on ties (standard "fractional ranking"), 1-indexed —
    shared by this module's pooled analysis and src.research.ic's
    cross-sectional Information Coefficient."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def spearman_correlation(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 2:
        return None
    return pearson_correlation(rank_values(xs), rank_values(ys))


def analyze_feature(rows: Sequence[dict], feature_col: str, target_col: str, *, n_quantiles: int = 5) -> FeatureAnalysisResult:
    """Evaluates whether `feature_col` has a measurable relationship with
    `target_col` (a future-return column — see src/research/targets.py).
    Rows with a None in either column are dropped, never imputed."""
    paired = [
        (r[feature_col], r[target_col])
        for r in rows
        if r.get(feature_col) is not None and r.get(target_col) is not None
    ]
    if len(paired) < n_quantiles:
        return FeatureAnalysisResult(
            feature_name=feature_col,
            target_name=target_col,
            sample_count=len(paired),
            pearson_correlation=None,
            spearman_correlation=None,
            quantiles=(),
            significance_note="Insufficient non-null paired samples for analysis.",
        )

    paired.sort(key=lambda p: p[0])
    xs = [p[0] for p in paired]
    ys = [p[1] for p in paired]
    pearson = pearson_correlation(xs, ys)
    spearman = spearman_correlation(xs, ys)

    n = len(paired)
    quantiles: list[QuantileResult] = []
    for q in range(n_quantiles):
        lo = (n * q) // n_quantiles
        hi = (n * (q + 1)) // n_quantiles if q < n_quantiles - 1 else n
        bucket_returns = [p[1] for p in paired[lo:hi]]
        if not bucket_returns:
            continue
        quantiles.append(
            QuantileResult(
                quantile=q + 1,
                mean_future_return=mean(bucket_returns),
                median_future_return=sorted(bucket_returns)[len(bucket_returns) // 2],
                hit_rate=sum(1 for r in bucket_returns if r > 0) / len(bucket_returns),
                sample_count=len(bucket_returns),
                volatility=stdev(bucket_returns),
            )
        )

    significance_note = (
        "CAUTION: financial time-series returns — especially overlapping multi-bar "
        "future returns — are autocorrelated, so this correlation is NOT a valid "
        "i.i.d. significance test. Treat these numbers as descriptive/exploratory "
        "only, never as a p-value to act on directly."
    )
    if pearson is not None and n > 2 and abs(pearson) < 1:
        t_stat = pearson * math.sqrt((n - 2) / (1 - pearson**2))
        significance_note += f" (naive t-statistic ≈ {t_stat:.2f}, n={n})"

    return FeatureAnalysisResult(
        feature_name=feature_col,
        target_name=target_col,
        sample_count=n,
        pearson_correlation=pearson,
        spearman_correlation=spearman,
        quantiles=tuple(quantiles),
        significance_note=significance_note,
    )
