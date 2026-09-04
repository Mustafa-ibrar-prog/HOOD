"""Phase 32, Parts 9 & 10/21 (bucket-specific pieces) — temporal
robustness and two placebo/adversarial tests that don't already exist
in Phase 31's reusable battery: leave-one-period-out, and an explicit
equal-weight-vs-observation-weighted aggregation comparison.

Year/underlying/DTE-bucket("expiration")/moneyness-bucket/call-put
stratification, leave-one-underlying-out, and the temporal-alignment
shift test are all reused UNCHANGED from `phase31_robustness.py` — every
field it stratifies by (`timestamp.year`, `underlying_symbol`,
`expiration`, `moneyness_bucket`, `call_put`) exists on bucket rows too
(`expiration` is deliberately repurposed to hold the DTE-bucket string —
documented in `phase32_bucket_panel.py`'s row assembly). See
`phase32_campaign.py` for where that reuse is actually invoked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.options.phase32_bucket_evidence import (
    PerSymbolResult,
    per_symbol_relationships,
    pooled_time_series_relationship,
    symbol_balanced_pooled_relationship,
)
from src.options.phase32_hypotheses import MIN_SAMPLE


@dataclass(frozen=True)
class PeriodResult:
    period_label: str
    n_observations: int
    spearman_correlation: float | None


def split_into_periods(rows: Sequence[dict], *, n_periods: int = 2) -> list[tuple[str, list[dict]]]:
    """Splits `rows` into `n_periods` contiguous, roughly-equal-length
    real-date periods (chronological, never randomized) -- used for
    leave-one-period-out below and reported as its own robustness axis."""
    dated = sorted(rows, key=lambda r: r["timestamp"])
    if not dated:
        return []
    n = len(dated)
    chunk = max(1, n // n_periods)
    periods = []
    for i in range(n_periods):
        start, end = i * chunk, (n if i == n_periods - 1 else (i + 1) * chunk)
        chunk_rows = dated[start:end]
        if not chunk_rows:
            continue
        label = f"{chunk_rows[0]['timestamp'].date()}..{chunk_rows[-1]['timestamp'].date()}"
        periods.append((label, chunk_rows))
    return periods


def leave_one_period_out(
    rows: Sequence[dict], *, feature_col: str, target_col: str, n_periods: int = 4,
    min_observations: int = MIN_SAMPLE.min_pooled_observations,
) -> tuple[PeriodResult, ...]:
    """Part 10's "leave-one-period-out": for each of `n_periods`
    chronological chunks, recompute the pooled relationship EXCLUDING
    that chunk. A real relationship should not depend on any single
    period being included."""
    periods = split_into_periods(rows, n_periods=n_periods)
    out = []
    for i, (label, _chunk) in enumerate(periods):
        remaining = [r for j, (_lbl, chunk_rows) in enumerate(periods) if j != i for r in chunk_rows]
        result = pooled_time_series_relationship(remaining, feature_col=feature_col, target_col=target_col, min_observations=min_observations)
        out.append(PeriodResult(
            period_label=f"excluding_{label}", n_observations=len(remaining),
            spearman_correlation=(result.spearman_correlation if result else None),
        ))
    return tuple(out)


@dataclass(frozen=True)
class WeightingComparisonResult:
    observation_weighted_spearman: float | None  # plain pooled -- denser underlyings implicitly weigh more
    equal_weighted_spearman: float | None  # symbol-balanced -- every underlying counts once
    materially_disagree: bool  # True if signs differ, or both exist and differ by more than `disagreement_threshold`


def compare_equal_vs_observation_weighting(
    rows: Sequence[dict], *, feature_col: str, target_col: str, disagreement_threshold: float = 0.15,
) -> WeightingComparisonResult:
    """Part 10's "equal-weight vs observation-weighted aggregation": if
    these two disagree materially, the pooled result is likely an
    artifact of one underlying's much denser real coverage, not a
    genuine shared relationship -- exactly the failure mode Part 8 also
    asks to flag via `symbol_balanced_pooled_relationship.
    dominated_by_single_symbol`."""
    pooled = pooled_time_series_relationship(rows, feature_col=feature_col, target_col=target_col, min_observations=1)
    per_symbol = per_symbol_relationships(rows, feature_col=feature_col, target_col=target_col)
    balanced = symbol_balanced_pooled_relationship(per_symbol)

    obs_weighted = pooled.spearman_correlation if pooled else None
    eq_weighted = balanced.symbol_balanced_spearman

    disagree = False
    if obs_weighted is not None and eq_weighted is not None:
        disagree = (obs_weighted > 0) != (eq_weighted > 0) or abs(obs_weighted - eq_weighted) > disagreement_threshold
    return WeightingComparisonResult(observation_weighted_spearman=obs_weighted, equal_weighted_spearman=eq_weighted, materially_disagree=disagree)
