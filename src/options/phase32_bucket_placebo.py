"""Phase 32, Part 10/21 — the remaining placebo/adversarial tests.

Most of Part 10's required battery is DIRECT REUSE, not rebuilt here:
  - "shuffled feature"        -> `src.research.cross_sectional_placebo.shuffled_signal_placebo`
  - "shifted feature"         -> `src.research.cross_sectional_placebo.shifted_signal_placebo`
  - "shuffled target"         -> `src.research.cross_sectional_placebo.time_shuffled_target_placebo`
  - "random bucket assignment"-> `src.options.placebo_extensions.symbol_identity_shuffle_placebo`
    (reassigns each bucket-series' entire target history to a
    DIFFERENT bucket-series' feature history -- the direct bucket-level
    analogue of "randomly assign which bucket a set of stats belongs
    to")
  - "date-shift placebo"      -> `phase31_robustness.evaluate_temporal_alignment` (already run for Part 9)
  - "underlying-only control" -> `phase31_underlying_control.underlying_control_comparison` (Part 6)
  - "leave-one-symbol-out"    -> `phase31_robustness.evaluate_robustness`'s `leave_one_underlying_out` (Part 9)
  - "leave-one-period-out"    -> `phase32_bucket_robustness.leave_one_period_out` (new, Part 9/10)
  - "equal-weight vs observation-weighted aggregation" -> `phase32_bucket_robustness.compare_equal_vs_observation_weighting`

This module adds the ONE genuinely new piece: top-outlier removal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.options.phase32_bucket_evidence import cross_sectional_relationship
from src.options.phase32_hypotheses import MIN_SAMPLE


@dataclass(frozen=True)
class OutlierRemovalResult:
    fraction_trimmed_each_tail: float
    n_before: int
    n_after: int
    ic_before: float | None
    ic_after: float | None
    outlier_dependent: bool


def trim_target_outliers(rows: Sequence[dict], *, target_col: str, fraction_each_tail: float = 0.01) -> list[dict]:
    """Removes the top/bottom `fraction_each_tail` of REAL target values
    (never a feature value -- Part 10 asks specifically about outlier
    OUTCOMES, not outlier inputs). Rows with a `None` target are kept
    (they carry no target-outlier risk and downstream min-sample checks
    still apply to them normally)."""
    values = sorted(r[target_col] for r in rows if r.get(target_col) is not None)
    if len(values) < 20:
        return list(rows)
    n = len(values)
    lo_cut, hi_cut = values[int(n * fraction_each_tail)], values[int(n * (1 - fraction_each_tail)) - 1]
    return [r for r in rows if r.get(target_col) is None or lo_cut <= r[target_col] <= hi_cut]


def outlier_removal_test(
    rows: Sequence[dict], *, feature_col: str, target_col: str, fraction_each_tail: float = 0.01,
    min_universe_size: int = MIN_SAMPLE.min_cross_sectional_peer_group, outlier_tolerance: float = 0.5,
) -> OutlierRemovalResult:
    """Recomputes the cross-sectional relationship after trimming
    target-value outliers; flags `outlier_dependent=True` if the IC's
    sign flips or its magnitude drops by more than `1 - outlier_tolerance`."""
    before = cross_sectional_relationship(rows, feature_col=feature_col, target_col=target_col, min_universe_size=min_universe_size)
    trimmed = trim_target_outliers(rows, target_col=target_col, fraction_each_tail=fraction_each_tail)
    after = cross_sectional_relationship(trimmed, feature_col=feature_col, target_col=target_col, min_universe_size=min_universe_size)

    ic_before = before.report.ic_summary.average_ic if (before.applicable and before.report) else None
    ic_after = after.report.ic_summary.average_ic if (after.applicable and after.report) else None

    dependent = False
    if ic_before is not None and ic_after is not None and abs(ic_before) > 1e-9:
        dependent = (ic_before > 0) != (ic_after > 0) or (ic_after / ic_before) < outlier_tolerance

    return OutlierRemovalResult(
        fraction_trimmed_each_tail=fraction_each_tail, n_before=len(rows), n_after=len(trimmed),
        ic_before=ic_before, ic_after=ic_after, outlier_dependent=dependent,
    )
