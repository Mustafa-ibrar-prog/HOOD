"""Phase 33, Part E/24 — DTE-balanced, moneyness-balanced, and
call/put-balanced pooled relationships.

Part E: "Evaluate: all eligible buckets pooled, DTE-balanced,
moneyness-balanced, call/put-balanced where sample permits." Generalizes
`phase32_bucket_evidence.PerSymbolResult`/`SymbolBalancedResult`/
`per_symbol_relationships`/`symbol_balanced_pooled_relationship` -- the
EXACT same equal-weight-average-of-per-group-correlation pattern Phase
32 already used to avoid one underlying silently dominating a pooled
result, parameterized here by an arbitrary grouping key instead of being
hardcoded to `underlying_symbol`. Reuses `src.research.analysis.
analyze_feature`/`mean` directly, unchanged -- no new correlation math.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Sequence

from src.options.phase32_hypotheses import MIN_SAMPLE
from src.research.analysis import FeatureAnalysisResult, analyze_feature, mean


def _clean_pairs(rows: Sequence[dict], feature_col: str, target_col: str) -> list[dict]:
    return [r for r in rows if r.get(feature_col) is not None and r.get(target_col) is not None]


@dataclass(frozen=True)
class GroupResult:
    group_label: str  # e.g. "dte_bucket", "moneyness_bucket", "call_put"
    group_value: str
    n_observations: int
    result: FeatureAnalysisResult | None
    reason: str


def group_relationships(
    rows: Sequence[dict], *, feature_col: str, target_col: str, key_fn: Callable[[dict], str], group_label: str,
    n_quantiles: int = 5, min_observations: int = MIN_SAMPLE.min_symbol_level_observations,
) -> tuple[GroupResult, ...]:
    """Part E: one relationship per real group value present in `rows`
    (e.g. every DTE bucket, every moneyness bucket, every call/put side)
    -- never a group invented that has no real observations."""
    by_group: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_group[str(key_fn(r))].append(r)

    out = []
    for group_value in sorted(by_group):
        clean = _clean_pairs(by_group[group_value], feature_col, target_col)
        if len(clean) < min_observations:
            out.append(GroupResult(group_label, group_value, len(clean), None, f"{len(clean)} < min_observations={min_observations}"))
            continue
        out.append(GroupResult(group_label, group_value, len(clean), analyze_feature(clean, feature_col, target_col, n_quantiles=n_quantiles), ""))
    return tuple(out)


@dataclass(frozen=True)
class GroupBalancedResult:
    group_label: str
    n_groups_eligible: int
    group_balanced_spearman: float | None
    group_balanced_pearson: float | None
    dominated_by_single_group: bool
    dominant_group_value: str | None
    dominant_group_share: float | None


def group_balanced_pooled_relationship(group_results: tuple[GroupResult, ...], *, dominance_threshold: float = 0.60) -> GroupBalancedResult:
    """The X-balanced pooled statistic: an equal-weight AVERAGE of each
    eligible group's own correlation, never a raw row-count-weighted
    pool -- same rationale as Phase 32's symbol-balanced average (a
    dense DTE bucket, moneyness bucket, or call/put side must not
    silently dominate)."""
    label = group_results[0].group_label if group_results else ""
    eligible = [g for g in group_results if g.result is not None]
    total_obs = sum(g.n_observations for g in group_results)

    spearmans = [g.result.spearman_correlation for g in eligible if g.result.spearman_correlation is not None]
    pearsons = [g.result.pearson_correlation for g in eligible if g.result.pearson_correlation is not None]

    dominant = max(group_results, key=lambda g: g.n_observations) if group_results else None
    dominant_share = (dominant.n_observations / total_obs) if (dominant is not None and total_obs > 0) else None
    dominated = dominant_share is not None and dominant_share >= dominance_threshold

    return GroupBalancedResult(
        group_label=label, n_groups_eligible=len(eligible),
        group_balanced_spearman=(mean(spearmans) if spearmans else None),
        group_balanced_pearson=(mean(pearsons) if pearsons else None),
        dominated_by_single_group=dominated,
        dominant_group_value=(dominant.group_value if dominant else None),
        dominant_group_share=dominant_share,
    )
