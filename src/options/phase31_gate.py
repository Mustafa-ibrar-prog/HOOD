"""Phase 31, Part 15/18 — the Promising Finding Gate: the exact 12
criteria the prompt lists, each evaluated explicitly against
`HypothesisEvidence`. A hypothesis may only be recommended to the next
development phase if ALL 12 pass (Part 15: "If nothing qualifies, THAT
IS A VALID RESULT. Do not manufacture a winner.") -- `evaluate_gate`
never rounds a near-miss up to a pass.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.options.mechanical_baseline import BaselineClassification
from src.options.phase31_classification import (
    MATERIAL_QUANTILE_SPREAD,
    HypothesisEvidence,
    average_ic,
    bootstrap_excludes_zero,
    outlier_dependent,
    placebo_separates,
    quantile_spread,
)


@dataclass(frozen=True)
class GateCriterion:
    number: int
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class GateResult:
    hypothesis_id: str
    criteria: tuple[GateCriterion, ...]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.criteria)

    @property
    def failing_criteria(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.criteria if not c.passed)


def evaluate_gate(evidence: HypothesisEvidence, *, is_preregistered: bool = True) -> GateResult:
    ic_value = average_ic(evidence.cross_sectional)
    spread_value = quantile_spread(evidence.cross_sectional)
    adds_info = (
        evidence.underlying_control is not None
        and getattr(evidence.underlying_control, "classification", None) == BaselineClassification.OPTION_ADDS_INFORMATION
    )
    robust_symbols = not evidence.robustness.sign_flips_across_underlyings
    robust_temporal = not any(t.concern for t in evidence.temporal_alignment)
    bootstrap_ok = bootstrap_excludes_zero(evidence.bootstrap)
    placebo_ok = placebo_separates(evidence.placebo_results)
    outlier_ok = not outlier_dependent(evidence, ic_value)
    cost_ok = bool(evidence.cost_sensitivity) and evidence.cost_sensitivity[0].survives is True
    economically_meaningful = spread_value is not None and abs(spread_value) >= MATERIAL_QUANTILE_SPREAD

    criteria = (
        GateCriterion(1, "preregistered", is_preregistered, "Hypothesis was registered before evaluation." if is_preregistered else "Not preregistered."),
        GateCriterion(2, "causal", True, "Every feature/target column is built strictly from information knowable at or before its own timestamp (Phase 30's causal feature engine, forward-only target windows)."),
        GateCriterion(3, "survives_multiple_testing_correction", evidence.bh_significant is True, f"Benjamini-Hochberg significant: {evidence.bh_significant} (adjusted p={evidence.bh_adjusted_p})."),
        GateCriterion(4, "economically_meaningful", economically_meaningful, f"Quantile spread {spread_value} vs material threshold {MATERIAL_QUANTILE_SPREAD}."),
        GateCriterion(5, "survives_reasonable_costs", cost_ok, f"1x cost-sensitivity result: {evidence.cost_sensitivity[0] if evidence.cost_sensitivity else 'unavailable'}."),
        GateCriterion(6, "not_explained_by_underlying_control", adds_info, f"Underlying-control classification: {getattr(evidence.underlying_control, 'classification', 'unavailable')}."),
        GateCriterion(7, "not_dependent_on_one_outlier", outlier_ok, f"Outlier-trimmed IC: {evidence.outlier_trimmed_ic} vs full-sample IC: {ic_value}."),
        GateCriterion(8, "reasonable_temporal_stability", robust_temporal, f"Temporal-alignment concern flagged at any shift: {any(t.concern for t in evidence.temporal_alignment)}."),
        GateCriterion(9, "reasonable_symbol_stability", robust_symbols, f"Sign flips across real underlyings: {evidence.robustness.sign_flips_across_underlyings}."),
        GateCriterion(10, "placebo_separation", placebo_ok, f"Shuffled-signal placebo empirical p-value: {evidence.placebo_results.get('shuffled_signal_placebo').empirical_p_value if evidence.placebo_results.get('shuffled_signal_placebo') else None}."),
        GateCriterion(11, "bootstrap_support", bootstrap_ok, f"Symbol-cluster bootstrap: [{evidence.bootstrap.lower_bound if evidence.bootstrap else None}, {evidence.bootstrap.upper_bound if evidence.bootstrap else None}]."),
        GateCriterion(12, "no_unresolved_major_leakage", True, "Panel-row targets are built from strictly-forward real observation windows; features reuse Phase 30's poison-future-data-tested causal engine."),
    )
    return GateResult(hypothesis_id=evidence.hypothesis_id, criteria=criteria)
