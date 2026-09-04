"""Phase 33, Part G/24 — reproducing Phase 23's specific adversarial
checks at the coarse-grained (bucket) level: non-overlapping windows,
and real EXPIRATION/year concentration.

Most of Part G is already covered by reusing Phase 31/32 machinery
UNCHANGED inside `phase33_replication_campaign.evaluate_replication_hypothesis`
(`phase31_robustness.evaluate_robustness` already stratifies by year,
underlying, DTE-bucket [bucket rows repurpose the `expiration` field to
hold the DTE-bucket string -- Phase 32's documented convention], real
moneyness bucket, and call/put; `phase32_bucket_placebo.outlier_removal_test`
already does top-outlier removal; `phase32_bucket_robustness.
leave_one_period_out` already does per-period robustness; the placebo
battery already covers shuffled-feature/shifted-feature/shuffled-target).

THIS module adds the two things nothing else in the codebase computes:

1. **Non-overlapping windows** (Phase 23 Part 9's specific test): take
   every `horizon`-th real date per bucket-series so consecutive forward
   windows never overlap, then re-evaluate the SAME relationship on that
   thinned subsample -- exactly Phase 23's own non-overlap methodology,
   applied here to bucket-series instead of individual contracts.

2. **Real expiration / year concentration** (Phase 23 Part 11's finding
   that "2023 concentration" was actually "one real expiration + a
   smaller symbol subset"): bucket-day rows aggregate away the real
   expiration identity (Phase 32 repurposes that field for the DTE
   bucket), so this must be computed on the underlying CONTRACT-DAY rows
   (Phase 31's `build_panel_rows` output, which still carries the real
   `expiration` column) that feed into the evaluated bucket panel --
   never invented from the bucket rows themselves, which structurally
   cannot answer this question.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Sequence

from src.options.phase32_bucket_evidence import cross_sectional_relationship, pooled_time_series_relationship
from src.options.phase32_hypotheses import MIN_SAMPLE


@dataclass(frozen=True)
class NonOverlapResult:
    horizon: int
    n_series: int
    n_rows_before: int
    n_rows_after: int
    pooled_before: object
    pooled_after: object
    cross_sectional_before_ic: float | None
    cross_sectional_after_ic: float | None
    cross_sectional_after_p: float | None


def non_overlapping_subsample(bucket_rows: Sequence[dict], *, horizon: int, series_key_col: str = "option_id") -> list[dict]:
    """Keeps every `horizon`-th real date within each bucket-series
    (sorted chronologically), so no two retained rows' `horizon`-day
    forward windows can overlap -- Phase 23 Part 9's exact
    non-overlapping-window construction, generalized from
    "every 5th contract-day" to "every horizon-th bucket-series-date.\""""
    by_series: dict[str, list[dict]] = defaultdict(list)
    for r in bucket_rows:
        by_series[r[series_key_col]].append(r)
    out: list[dict] = []
    for rows in by_series.values():
        rows_sorted = sorted(rows, key=lambda r: r["timestamp"])
        out.extend(rows_sorted[i] for i in range(0, len(rows_sorted), max(horizon, 1)))
    return out


def evaluate_non_overlap(
    bucket_rows: Sequence[dict], *, feature_col: str, target_col: str, horizon: int,
    series_key_col: str = "option_id", min_universe_size: int = MIN_SAMPLE.min_cross_sectional_peer_group,
) -> NonOverlapResult:
    subsample = non_overlapping_subsample(bucket_rows, horizon=horizon, series_key_col=series_key_col)
    pooled_before = pooled_time_series_relationship(bucket_rows, feature_col=feature_col, target_col=target_col)
    pooled_after = pooled_time_series_relationship(subsample, feature_col=feature_col, target_col=target_col)
    cs_before = cross_sectional_relationship(bucket_rows, feature_col=feature_col, target_col=target_col, min_universe_size=min_universe_size)
    cs_after = cross_sectional_relationship(subsample, feature_col=feature_col, target_col=target_col, min_universe_size=min_universe_size)

    ic_before = cs_before.report.ic_summary.average_ic if (cs_before.applicable and cs_before.report) else None
    ic_after = cs_after.report.ic_summary.average_ic if (cs_after.applicable and cs_after.report) else None
    p_after = cs_after.report.ic_p_value if (cs_after.applicable and cs_after.report) else None

    return NonOverlapResult(
        horizon=horizon, n_series=len({r[series_key_col] for r in bucket_rows}),
        n_rows_before=len(bucket_rows), n_rows_after=len(subsample),
        pooled_before=pooled_before, pooled_after=pooled_after,
        cross_sectional_before_ic=ic_before, cross_sectional_after_ic=ic_after, cross_sectional_after_p=p_after,
    )


@dataclass(frozen=True)
class ConcentrationReport:
    dimension: str  # "expiration" | "year"
    n_rows: int
    counts: dict[str, int]
    top_value: str | None
    top_share: float | None
    n_distinct: int


def _concentration(rows: Sequence[dict], *, dimension: str, key_fn) -> ConcentrationReport:
    values = [str(key_fn(r)) for r in rows if key_fn(r) is not None]
    counts = dict(Counter(values))
    n_rows = len(values)
    if not counts:
        return ConcentrationReport(dimension=dimension, n_rows=0, counts={}, top_value=None, top_share=None, n_distinct=0)
    top_value, top_count = max(counts.items(), key=lambda kv: kv[1])
    return ConcentrationReport(
        dimension=dimension, n_rows=n_rows, counts=counts, top_value=top_value,
        top_share=(top_count / n_rows if n_rows else None), n_distinct=len(counts),
    )


def expiration_concentration(contract_day_rows: Sequence[dict]) -> ConcentrationReport:
    """Real expiration concentration -- computed on the CONTRACT-DAY
    panel (never the bucket panel, which has no real expiration column
    left to inspect), reporting each real expiration's share of the
    total contract-day rows that fed the replication's bucket panel."""
    return _concentration(contract_day_rows, dimension="expiration", key_fn=lambda r: r.get("expiration"))


def year_concentration(contract_day_rows: Sequence[dict]) -> ConcentrationReport:
    return _concentration(contract_day_rows, dimension="year", key_fn=lambda r: r["timestamp"].year if r.get("timestamp") else None)
