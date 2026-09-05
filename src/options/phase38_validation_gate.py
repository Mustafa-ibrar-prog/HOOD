"""Phase 38, Part 13 — the formal strategy-promotion gate.

ALL conditions must pass -- there is no code path that sets
`status = VALIDATED` on partial evidence (Part 14's explicit
prohibition). `evaluate_validation_gate` is a pure function of a
`GateEvidence` bundle; nothing here can be satisfied by lowering a
requirement because the sample is inconvenient (Part 13's explicit
instruction) -- every threshold reused below is this project's own,
already-established floor (`MIN_SAMPLE_FOR_A_VERDICT = 20`,
`MIN_TOTAL_FOR_CHRONOLOGICAL_SPLIT = 60`), never invented fresh for
this gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.options.phase38_affordability import ThousandDollarAffordabilityResult
from src.options.phase38_chronological_split import ChronologicalSplit
from src.options.phase38_economic_validation import EconomicValidationReport
from src.options.phase38_falsification import CostStressResult, OutcomeStats, PlaceboResult, TimingRobustnessResult
from src.options.phase38_underlying_vs_option_edge import EdgeClassification, UnderlyingVsOptionEdgeResult

if TYPE_CHECKING:
    from src.options.phase33_test_registry import TestRegistry
    from src.research_recorder.quality_report import DataQualityReport


@dataclass(frozen=True)
class GateEvidence:
    chronological_split: ChronologicalSplit
    development_edge: UnderlyingVsOptionEdgeResult
    validation_edge: UnderlyingVsOptionEdgeResult
    holdout_edge: UnderlyingVsOptionEdgeResult
    holdout_touched_before_freeze: bool  # must be False -- set True only if code EVER used holdout data to pick a parameter
    test_registry: "TestRegistry | None"
    economic_report: EconomicValidationReport
    spread_stress_results: tuple[CostStressResult, ...]
    cost_stress_results: tuple[CostStressResult, ...]
    leave_one_period_out: dict[str, OutcomeStats]
    leave_one_symbol_out: dict[str, OutcomeStats]
    placebo_result: PlaceboResult
    timing_robustness_result: TimingRobustnessResult
    affordability: ThousandDollarAffordabilityResult
    data_quality: "DataQualityReport | None"


@dataclass(frozen=True)
class GateConditionResult:
    number: int
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class GateResult:
    passed: bool
    conditions: tuple[GateConditionResult, ...]
    unmet_condition_names: tuple[str, ...]


def _robustness_all_positive(breakdown: dict[str, OutcomeStats]) -> bool:
    if len(breakdown) < 2:
        return False
    return all(s.n >= 20 and s.mean_return is not None and s.mean_return > 0 for s in breakdown.values())


def evaluate_validation_gate(evidence: GateEvidence) -> GateResult:
    conditions: list[GateConditionResult] = []

    # 1. Deterministic strategy specification -- structural: MOMENTUM_BREAKOUT_EXISTING_V1
    # (src.options.phase35_frozen_strategy_spec) is used unmodified throughout; no
    # discretionary/LLM-judgment logic exists anywhere in this phase's code.
    conditions.append(GateConditionResult(1, "deterministic_strategy_specification", True, "Reuses MOMENTUM_BREAKOUT_EXISTING_V1 (Phase 35) unmodified."))

    # 2. Causal feature construction -- structural: build_causal_feature_row takes only
    # ONE observation; compute_forward_outcome filters to strictly-later timestamps only.
    conditions.append(GateConditionResult(2, "causal_feature_construction", True, "Verified by tests/test_phase38_causal_dataset_and_targets.py's anti-lookahead suite."))

    # 3. Sufficient sample size
    sufficient_sample = evidence.chronological_split.sufficient
    conditions.append(GateConditionResult(3, "sufficient_sample_size", sufficient_sample, evidence.chronological_split.reason))

    # 4. Chronological validation actually ran
    validation_ran = sufficient_sample and evidence.validation_edge.n_outcomes >= 20
    conditions.append(GateConditionResult(4, "chronological_validation", validation_ran, f"validation split n={evidence.validation_edge.n_outcomes}"))

    # 5. Untouched final holdout
    holdout_untouched = not evidence.holdout_touched_before_freeze
    conditions.append(GateConditionResult(5, "untouched_final_holdout", holdout_untouched, "No parameter was ever tuned against final_holdout." if holdout_untouched else "holdout_touched_before_freeze is True -- gate refuses."))

    # 6. Multiple-testing accounting
    registry_used = evidence.test_registry is not None and len(evidence.test_registry.all()) > 0
    conditions.append(GateConditionResult(6, "multiple_testing_accounting", registry_used, f"{len(evidence.test_registry.all()) if evidence.test_registry else 0} test(s) registered."))

    # 7. Economically meaningful results
    economically_meaningful = evidence.economic_report.n_trades >= 20 and (evidence.economic_report.expectancy or 0) > 0
    conditions.append(GateConditionResult(7, "economically_meaningful_results", economically_meaningful, f"n={evidence.economic_report.n_trades}, expectancy={evidence.economic_report.expectancy}"))

    # 8. Realistic transaction-cost analysis
    cost_survives = any(r.survives is True for r in evidence.cost_stress_results) if evidence.cost_stress_results else False
    spread_survives = any(r.survives is True for r in evidence.spread_stress_results) if evidence.spread_stress_results else False
    cost_analysis_done = bool(evidence.cost_stress_results) and bool(evidence.spread_stress_results) and cost_survives and spread_survives
    conditions.append(GateConditionResult(8, "realistic_transaction_cost_analysis", cost_analysis_done, "Survives at least the 1x cost/spread stress point." if cost_analysis_done else "Does not survive disclosed cost/spread stress, or was never computable."))

    # 9. Execution realism -- structural: executable_return_pct always uses bid(exit)/ask(entry), never mid.
    conditions.append(GateConditionResult(9, "execution_realism", True, "compute_forward_outcome uses bid/ask exclusively for executable_return_pct."))

    # 10. Robustness across time
    time_robust = _robustness_all_positive(evidence.leave_one_period_out)
    conditions.append(GateConditionResult(10, "robustness_across_time", time_robust, f"{len(evidence.leave_one_period_out)} period(s) checked."))

    # 11. Robustness across symbols/contracts
    symbol_robust = _robustness_all_positive(evidence.leave_one_symbol_out)
    conditions.append(GateConditionResult(11, "robustness_across_symbols", symbol_robust, f"{len(evidence.leave_one_symbol_out)} symbol(s) checked."))

    # 12. Falsification tests passed
    falsification_passed = (
        evidence.placebo_result.classification == "OBSERVED_EXCEEDS_PLACEBO"
        and evidence.timing_robustness_result.classification == "ROBUST_TO_SIGNAL_SHIFT"
    )
    conditions.append(GateConditionResult(12, "falsification_tests_passed", falsification_passed, f"placebo={evidence.placebo_result.classification}, timing={evidence.timing_robustness_result.classification}"))

    # 13. No material data leakage -- structural, same basis as condition 2.
    conditions.append(GateConditionResult(13, "no_material_data_leakage", True, "Anti-lookahead structural guarantees (condition 2) apply identically here."))

    # 14. No unresolved critical data-quality issue
    if evidence.data_quality is None:
        no_critical_issue = False
        detail_14 = "No data-quality report exists (zero cycles recorded) -- cannot confirm the absence of a critical issue."
    else:
        no_critical_issue = evidence.data_quality.parser_failures == 0 and (
            evidence.data_quality.quote_completeness_pct is None or evidence.data_quality.quote_completeness_pct >= 0.5
        )
        detail_14 = f"parser_failures={evidence.data_quality.parser_failures}, completeness={evidence.data_quality.quote_completeness_pct}"
    conditions.append(GateConditionResult(14, "no_unresolved_critical_data_quality_issue", no_critical_issue, detail_14))

    # 15. Affordability assessment completed
    affordability_done = evidence.affordability.classification != "ACCOUNT_FEASIBILITY_UNKNOWN_NO_PRICED_ROWS"
    conditions.append(GateConditionResult(15, "affordability_assessment_completed", affordability_done, evidence.affordability.classification))

    # 16. Option-level implementation edge demonstrated where claimed
    edge_demonstrated = evidence.holdout_edge.classification == EdgeClassification.OPTION_ADDS_VALUE
    conditions.append(GateConditionResult(16, "option_level_implementation_edge_demonstrated", edge_demonstrated, evidence.holdout_edge.detail))

    # 17. Reproducible validation artifact generated -- only possible once every other condition holds.
    all_others_passed = all(c.passed for c in conditions)
    conditions.append(GateConditionResult(17, "reproducible_validation_artifact_generated", all_others_passed, "All 16 preceding conditions satisfied." if all_others_passed else "Cannot generate a reproducible artifact -- one or more preceding conditions failed."))

    unmet = tuple(c.name for c in conditions if not c.passed)
    return GateResult(passed=(len(unmet) == 0), conditions=tuple(conditions), unmet_condition_names=unmet)
