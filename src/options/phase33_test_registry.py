"""Phase 33, Part A/24 — the fixed multiple-testing accounting
infrastructure.

AUDIT FINDING (this phase's own investigation of Phase 32's
`phase32_campaign.run_campaign`): the ONLY p-value ever fed into
`multiple_testing_across_family` was each hypothesis's CROSS-SECTIONAL
IC p-value (`CrossSectionalAlphaReport.ic_p_value`, via
`phase31_robustness.multiple_testing_across_family`). The pooled
time-series test (`pooled_time_series_relationship`), every per-symbol
test (`per_symbol_relationships`), the symbol-balanced pooled statistic,
leave-one-underlying-out, and leave-one-period-out were all COMPUTED and
reported, but NONE of their p-values (where one exists) ever entered the
correction. This is exactly the gap Phase 32's own report disclosed
(§12): "the formal multiple-testing correction is anchored to each
hypothesis's cross-sectional IC p-value... every p-value defaulted to
1.0... a genuine methodological gap."

THE FIX is this module: an explicit, append-only `TestRegistry` that
every inferential test (from ANY aggregation method) must be registered
into BEFORE `apply_correction` runs — never a data structure a future
phase's campaign script can quietly forget to feed a result into,
because `phase32_campaign.run_campaign` (and Phase 33's own replication
campaign) now BUILD this registry directly as part of evaluating each
hypothesis, not as an afterthought computed from already-discarded
results.

CORRECTION FAMILIES, deliberately kept separate (a genuine design
decision, not an oversight): `PRIMARY_FAMILY` holds every test that
directly answers "does this feature predict this target" (cross-
sectional, pooled time-series, per-symbol) — these compete for the same
false-discovery budget and are corrected together. `DIAGNOSTIC_FAMILY`
holds descriptive/robustness checks that don't have a well-defined null-
hypothesis p-value of their own (symbol-balanced averages, leave-one-out
point estimates) — registered for full accounting (Part A: "so future
research cannot accidentally omit a tested result"), but their
`correction_status` is honestly `NOT_APPLICABLE_NO_PVALUE`, never forced
into the primary correction. `PLACEBO_FAMILY` holds placebo empirical
p-values — a genuinely different statistical question (null-distribution
comparison, not a family of competing feature/target hypotheses), so
mixing them into `PRIMARY_FAMILY` would misrepresent what is actually
being corrected for.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from src.research.multiple_testing import CorrectedResult, MultipleTestingReport, benjamini_hochberg_fdr, bonferroni_correction, holm_bonferroni_correction
from src.research.stats_utils import two_tailed_p_value_from_z

PRIMARY_FAMILY = "primary_inferential"
DIAGNOSTIC_FAMILY = "diagnostic_robustness"
PLACEBO_FAMILY = "placebo_diagnostics"


def correlation_p_value(r: float | None, n: int) -> float | None:
    """Two-tailed p-value for H0: rho=0, given a correlation `r` from
    `n` paired real observations. Standard r-to-t transformation
    (t = r*sqrt((n-2)/(1-r^2))), converted to a p-value via THIS
    codebase's existing `two_tailed_p_value_from_z` normal
    approximation (`src.research.stats_utils` — the same one
    `cross_sectional_alpha.py` already uses for IC significance,
    reused here rather than a new approximation invented for this
    module). Documented there as inexact for small n; the same caveat
    applies here."""
    if r is None or n < 4 or abs(r) >= 1.0:
        return None
    t = r * math.sqrt((n - 2) / (1 - r ** 2))
    return two_tailed_p_value_from_z(t)


@dataclass(frozen=True)
class InferentialTestRecord:
    hypothesis_id: str
    feature_family: str
    feature: str
    target: str
    horizon: int
    aggregation_method: str  # "cross_sectional" | "pooled_time_series" | "per_symbol" | "symbol_balanced" |
                              # "leave_one_symbol_out" | "leave_one_period_out" | "placebo:<name>" | "outlier_removal" | ...
    bucket_definition: str  # "fine" | "coarse" | "contract_level"
    underlying: str  # a specific symbol, or "ALL" for pooled/cross-sectional tests
    test_type: str  # e.g. "cross_sectional_ic" | "pearson_correlation_p" | "spearman_correlation_p" | "placebo_empirical_p"
    sample_size: int
    p_value: float | None
    effect_size: float | None
    correction_family: str
    correction_status: str = "PENDING"  # filled in by apply_correction(); "NOT_APPLICABLE_NO_PVALUE" if p_value is None


class TestRegistry:
    """Append-only (Phase 4/7's established convention for research
    records) -- `register()` never overwrites an existing record for
    the same (hypothesis_id, aggregation_method, underlying) triple;
    call `register_or_replace()` explicitly if a genuine re-run is
    intended, so an accidental double-registration is caught, not
    silently duplicated or silently overwritten."""

    def __init__(self) -> None:
        self._records: list[InferentialTestRecord] = []

    def register(self, record: InferentialTestRecord) -> InferentialTestRecord:
        key = (record.hypothesis_id, record.aggregation_method, record.underlying, record.target)
        for existing in self._records:
            if (existing.hypothesis_id, existing.aggregation_method, existing.underlying, existing.target) == key:
                raise ValueError(f"a test is already registered for {key} -- use register_or_replace() for a genuine re-run")
        self._records.append(record)
        return record

    def register_or_replace(self, record: InferentialTestRecord) -> InferentialTestRecord:
        key = (record.hypothesis_id, record.aggregation_method, record.underlying, record.target)
        self._records = [
            r for r in self._records
            if (r.hypothesis_id, r.aggregation_method, r.underlying, r.target) != key
        ]
        self._records.append(record)
        return record

    def all(self) -> tuple[InferentialTestRecord, ...]:
        return tuple(self._records)

    def by_family(self, correction_family: str) -> tuple[InferentialTestRecord, ...]:
        return tuple(r for r in self._records if r.correction_family == correction_family)

    def by_hypothesis(self, hypothesis_id: str) -> tuple[InferentialTestRecord, ...]:
        return tuple(r for r in self._records if r.hypothesis_id == hypothesis_id)

    def update_correction_status(self, updated: Sequence[InferentialTestRecord]) -> None:
        """Replaces registered records in place with corrected-status
        copies (same identity key) -- used by `apply_correction`."""
        by_key = {(r.hypothesis_id, r.aggregation_method, r.underlying, r.target): r for r in updated}
        self._records = [
            by_key.get((r.hypothesis_id, r.aggregation_method, r.underlying, r.target), r)
            for r in self._records
        ]


@dataclass(frozen=True)
class CorrectionResult:
    correction_family: str
    n_registered: int  # total records in this family, INCLUDING those with no p-value
    n_with_p_value: int  # how many actually entered the correction
    bonferroni: MultipleTestingReport | None
    holm: MultipleTestingReport | None
    benjamini_hochberg: MultipleTestingReport | None


def _record_label(record: InferentialTestRecord) -> str:
    return f"{record.hypothesis_id}|{record.aggregation_method}|{record.underlying}|{record.target}"


def apply_correction(registry: TestRegistry, correction_family: str, *, alpha: float = 0.05) -> CorrectionResult:
    """The ONLY place multiple-testing correction happens in Phase 33 —
    operates on every record in `correction_family`, testable or not,
    so `n_registered` vs `n_with_p_value` makes the omission Phase 32
    had structurally impossible to reproduce silently."""
    family_records = registry.by_family(correction_family)
    testable = [r for r in family_records if r.p_value is not None]
    labeled_p = [(_record_label(r), r.p_value) for r in testable]

    if not labeled_p:
        registry.update_correction_status([_with_status(r, "NOT_APPLICABLE_NO_PVALUE") for r in family_records])
        return CorrectionResult(correction_family, len(family_records), 0, None, None, None)

    bonferroni = bonferroni_correction(labeled_p, alpha=alpha)
    holm = holm_bonferroni_correction(labeled_p, alpha=alpha)
    bh = benjamini_hochberg_fdr(labeled_p, alpha=alpha)
    bh_significant_labels = {r.label for r in bh.results if r.significant_at_alpha}

    updated_records = []
    for r in family_records:
        if r.p_value is None:
            updated_records.append(_with_status(r, "NOT_APPLICABLE_NO_PVALUE"))
        else:
            status = "SIGNIFICANT_AFTER_BH" if _record_label(r) in bh_significant_labels else "NOT_SIGNIFICANT_AFTER_BH"
            updated_records.append(_with_status(r, status))
    registry.update_correction_status(updated_records)

    return CorrectionResult(correction_family, len(family_records), len(testable), bonferroni, holm, bh)


def _with_status(record: InferentialTestRecord, status: str) -> InferentialTestRecord:
    import dataclasses
    return dataclasses.replace(record, correction_status=status)
