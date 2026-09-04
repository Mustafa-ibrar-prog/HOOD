"""Phase 32, Part 8/21 — pooled time-series, cross-sectional, per-symbol,
and symbol-balanced pooled relationships.

B (cross-sectional) reuses Phase 31's `phase31_evidence.
evaluate_cross_sectional_evidence` UNMODIFIED — bucket rows already carry
`cs_group_key=(date,)` (every bucket that exists on a real date, across
ALL underlyings, is one peer group: Part 8B's "cross-sectional
relationship" at the bucket level), so no new economic-scoping logic is
needed. A (pooled time-series) reuses `src.research.analysis.
analyze_feature` directly (the project's existing pooled, non-cross-
sectional correlation+quantile tool). C (per-symbol) and D
(symbol-balanced pooled) are new — thin wrappers around A, since neither
existed at this granularity before.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

from src.options.phase31_evidence import CrossSectionalEvidence, evaluate_cross_sectional_evidence
from src.options.phase32_hypotheses import MIN_SAMPLE
from src.research.analysis import FeatureAnalysisResult, analyze_feature, mean


def _clean_pairs(rows: Sequence[dict], feature_col: str, target_col: str) -> list[dict]:
    return [r for r in rows if r.get(feature_col) is not None and r.get(target_col) is not None]


def pooled_time_series_relationship(
    rows: Sequence[dict], *, feature_col: str, target_col: str, n_quantiles: int = 5,
    min_observations: int = MIN_SAMPLE.min_pooled_observations,
) -> FeatureAnalysisResult | None:
    """Part 8A. `None` (never a fabricated result) if fewer than
    `min_observations` real (feature, target) pairs exist."""
    clean = _clean_pairs(rows, feature_col, target_col)
    if len(clean) < min_observations:
        return None
    return analyze_feature(clean, feature_col, target_col, n_quantiles=n_quantiles)


def cross_sectional_relationship(
    rows: Sequence[dict], *, feature_col: str, target_col: str, min_universe_size: int = MIN_SAMPLE.min_cross_sectional_peer_group,
) -> CrossSectionalEvidence:
    """Part 8B."""
    return evaluate_cross_sectional_evidence(rows, feature_col=feature_col, target_col=target_col, min_universe_size=min_universe_size)


@dataclass(frozen=True)
class PerSymbolResult:
    underlying: str
    n_observations: int
    result: FeatureAnalysisResult | None
    reason: str


def per_symbol_relationships(
    rows: Sequence[dict], *, feature_col: str, target_col: str, n_quantiles: int = 5,
    min_observations: int = MIN_SAMPLE.min_symbol_level_observations,
) -> tuple[PerSymbolResult, ...]:
    """Part 8C. One result per real underlying present in `rows`."""
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_symbol[r["underlying_symbol"]].append(r)

    out = []
    for underlying in sorted(by_symbol):
        clean = _clean_pairs(by_symbol[underlying], feature_col, target_col)
        if len(clean) < min_observations:
            out.append(PerSymbolResult(underlying, len(clean), None, f"{len(clean)} < min_observations={min_observations}"))
            continue
        out.append(PerSymbolResult(underlying, len(clean), analyze_feature(clean, feature_col, target_col, n_quantiles=n_quantiles), ""))
    return tuple(out)


@dataclass(frozen=True)
class SymbolBalancedResult:
    n_symbols_eligible: int
    symbol_balanced_spearman: float | None
    symbol_balanced_pearson: float | None
    dominated_by_single_symbol: bool
    dominant_symbol: str | None
    dominant_symbol_share: float | None


def symbol_balanced_pooled_relationship(
    per_symbol: tuple[PerSymbolResult, ...], *, dominance_threshold: float = 0.60,
) -> SymbolBalancedResult:
    """Part 8D: equal-weight AVERAGE of each eligible symbol's own
    correlation (never a raw row-count-weighted pool, which would let a
    denser underlying dominate silently) -- and Part 8's explicit
    "If a pooled result is driven by one underlying, flag it": computed
    from each symbol's OBSERVATION COUNT share among eligible symbols."""
    eligible = [p for p in per_symbol if p.result is not None]
    total_obs = sum(p.n_observations for p in per_symbol)  # ALL symbols, not just eligible -- a true share of the pool

    spearmans = [p.result.spearman_correlation for p in eligible if p.result.spearman_correlation is not None]
    pearsons = [p.result.pearson_correlation for p in eligible if p.result.pearson_correlation is not None]

    dominant = max(per_symbol, key=lambda p: p.n_observations) if per_symbol else None
    dominant_share = (dominant.n_observations / total_obs) if (dominant is not None and total_obs > 0) else None
    dominated = dominant_share is not None and dominant_share >= dominance_threshold

    return SymbolBalancedResult(
        n_symbols_eligible=len(eligible),
        symbol_balanced_spearman=mean(spearmans) if spearmans else None,
        symbol_balanced_pearson=mean(pearsons) if pearsons else None,
        dominated_by_single_symbol=dominated,
        dominant_symbol=(dominant.underlying if dominant else None),
        dominant_symbol_share=dominant_share,
    )
