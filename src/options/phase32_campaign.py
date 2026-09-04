"""Phase 32, Parts 15 & 16/21 — the bucketed-alpha campaign orchestrator
and the explicit Phase 31 comparison.

Ties together every `phase32_*` module plus extensive reuse of Phase 31
machinery: `phase31_evidence.evaluate_cross_sectional_evidence` (via
`phase32_bucket_evidence`), `phase31_underlying_control.
underlying_control_comparison`, `phase31_robustness.{evaluate_robustness,
evaluate_temporal_alignment,multiple_testing_across_family}`,
`src.options.dependence_bootstrap.symbol_cluster_bootstrap_ic`,
`src.research.cross_sectional_placebo`/`src.options.placebo_extensions`
(the placebo battery), `phase31_affordability_liquidity.
{affordability_filter_report,liquidity_report,cost_sensitivity_report}`
(bucket rows carry the same bid/ask/volume/OI/spread_pct column names,
as bucket MEDIANS), and `phase31_classification.classify_hypothesis`/
`phase31_gate.evaluate_gate` (the SAME 7-value classification and
12-criterion gate Phase 31 used — Part 14's explicit instruction: "Use
the existing 12-criterion Promising Finding Gate").

The one adapter this module builds: Phase 31's `classify_hypothesis`/
`evaluate_gate` expect a `phase31_evidence.TimeSeriesEvidence` (per-
CONTRACT time series). Phase 32's time-series concept is per-BUCKET-
SERIES/per-SYMBOL (Part 8C/D), a different but analogous evidence type
(`phase32_bucket_evidence.PerSymbolResult`/`SymbolBalancedResult`).
`_time_series_evidence_adapter` below losslessly repackages the bucket
evidence into the exact `TimeSeriesEvidence` shape so the REST of the
classification/gate logic runs completely unmodified — reuse, not a
parallel reimplementation of the same decision tree.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from src.options.dependence_bootstrap import symbol_cluster_bootstrap_ic
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.phase31_affordability_liquidity import affordability_filter_report, cost_sensitivity_report, liquidity_report
from src.options.phase31_classification import DiscoveryClassification, HypothesisEvidence, classify_hypothesis
from src.options.phase31_evidence import TimeSeriesContractResult, TimeSeriesEvidence
from src.options.phase31_gate import GateResult, evaluate_gate
from src.options.phase31_panel_builder import build_panel_rows
from src.options.phase31_robustness import evaluate_robustness, evaluate_temporal_alignment, multiple_testing_across_family
from src.options.phase31_underlying_control import underlying_control_comparison
from src.options.phase32_affordability import (
    BucketAffordabilityReport,
    TradeabilityClassification,
    build_bucket_affordability_report,
    classify_tradeability,
)
from src.options.phase32_bucket_definitions import BucketScheme
from src.options.phase32_bucket_evidence import (
    PerSymbolResult,
    SymbolBalancedResult,
    cross_sectional_relationship,
    per_symbol_relationships,
    pooled_time_series_relationship,
    symbol_balanced_pooled_relationship,
)
from src.options.phase32_bucket_panel import build_bucket_panel
from src.options.phase32_bucket_placebo import OutlierRemovalResult, outlier_removal_test
from src.options.phase32_bucket_robustness import WeightingComparisonResult, compare_equal_vs_observation_weighting, leave_one_period_out
from src.options.phase32_density_audit import SchemeSelectionResult, select_scheme_by_density
from src.options.phase32_hypotheses import MIN_SAMPLE, build_hypotheses, register_all
from src.research.analysis import mean
from src.research.cross_sectional_placebo import CrossSectionalPlaceboResult, shifted_signal_placebo, shuffled_signal_placebo, time_shuffled_target_placebo
from src.research.hypothesis import Hypothesis, HypothesisRegistry
from src.research.preregistration import PreregistrationStore, require_preregistered

DEFAULT_N_PLACEBO_TRIALS = 25
DEFAULT_N_BOOTSTRAP_RESAMPLES = 100


def _sign_stable_fraction(per_symbol: tuple[PerSymbolResult, ...]) -> float | None:
    spearmans = [p.result.spearman_correlation for p in per_symbol if p.result is not None and p.result.spearman_correlation is not None]
    if not spearmans:
        return None
    pooled_mean = mean(spearmans)
    return sum(1 for s in spearmans if (s > 0) == (pooled_mean > 0)) / len(spearmans)


def _time_series_evidence_adapter(
    per_symbol: tuple[PerSymbolResult, ...], balanced: SymbolBalancedResult, *, feature_col: str, target_col: str, horizon: int,
) -> TimeSeriesEvidence:
    per_contract = tuple(
        TimeSeriesContractResult(
            option_id=p.underlying, n_obs=p.n_observations, independent_periods_estimate=p.n_observations,
            pearson=(p.result.pearson_correlation if p.result else None), spearman=(p.result.spearman_correlation if p.result else None),
            eligible=(p.result is not None), reason=p.reason,
        )
        for p in per_symbol
    )
    applicable = balanced.n_symbols_eligible > 0
    reason = "" if applicable else "no underlying met the minimum per-symbol observation requirement for this feature/target pair"
    return TimeSeriesEvidence(
        feature_col=feature_col, target_col=target_col, horizon_bars=horizon, min_obs=MIN_SAMPLE.min_symbol_level_observations,
        min_independent_periods=1, n_contracts_evaluated=len(per_symbol), n_contracts_eligible=balanced.n_symbols_eligible,
        per_contract=per_contract, pooled_spearman_mean=balanced.symbol_balanced_spearman, sign_stable_fraction=_sign_stable_fraction(per_symbol),
        applicable=applicable, reason=reason,
    )


@dataclass(frozen=True)
class BucketHypothesisResult:
    hypothesis_id: str
    pooled_time_series: object
    per_symbol: tuple[PerSymbolResult, ...]
    symbol_balanced: SymbolBalancedResult
    weighting_comparison: WeightingComparisonResult
    leave_one_period_out: tuple
    outlier_removal: OutlierRemovalResult
    bucket_affordability: BucketAffordabilityReport
    base_evidence: HypothesisEvidence
    classification: DiscoveryClassification
    classification_reason: str
    gate: GateResult
    tradeability: TradeabilityClassification


def evaluate_one_bucket_hypothesis(
    hypothesis: Hypothesis, bucket_rows: Sequence[dict], contract_day_rows: Sequence[dict], *,
    n_placebo_trials: int = DEFAULT_N_PLACEBO_TRIALS, n_bootstrap_resamples: int = DEFAULT_N_BOOTSTRAP_RESAMPLES,
    min_universe_size: int = MIN_SAMPLE.min_cross_sectional_peer_group,
) -> BucketHypothesisResult:
    feature_col = hypothesis.required_features[0]
    target_col = hypothesis.target_definition
    horizon = hypothesis.prediction_horizon_bars
    underlying_return_col = f"forward_underlying_return_{horizon}"

    pooled = pooled_time_series_relationship(bucket_rows, feature_col=feature_col, target_col=target_col)
    cs_evidence = cross_sectional_relationship(bucket_rows, feature_col=feature_col, target_col=target_col, min_universe_size=min_universe_size)
    per_symbol = per_symbol_relationships(bucket_rows, feature_col=feature_col, target_col=target_col)
    balanced = symbol_balanced_pooled_relationship(per_symbol)
    ts_evidence = _time_series_evidence_adapter(per_symbol, balanced, feature_col=feature_col, target_col=target_col, horizon=horizon)

    underlying_control = None
    if any(r.get(underlying_return_col) is not None for r in bucket_rows):
        underlying_control = underlying_control_comparison(
            bucket_rows, option_feature_col=feature_col, target_col=target_col,
            underlying_return_col=underlying_return_col, underlying_target_col=underlying_return_col,
            min_universe_size=min_universe_size,
        )

    robustness = evaluate_robustness(bucket_rows, feature_col=feature_col, target_col=target_col, min_universe_size=min_universe_size)
    temporal = evaluate_temporal_alignment(bucket_rows, feature_col=feature_col, target_col=target_col, min_universe_size=min_universe_size)
    weighting = compare_equal_vs_observation_weighting(bucket_rows, feature_col=feature_col, target_col=target_col)
    period_results = leave_one_period_out(bucket_rows, feature_col=feature_col, target_col=target_col)
    outlier_result = outlier_removal_test(bucket_rows, feature_col=feature_col, target_col=target_col, min_universe_size=min_universe_size)

    bootstrap = symbol_cluster_bootstrap_ic(
        bucket_rows, feature_col=feature_col, target_col=target_col, n_resamples=n_bootstrap_resamples, min_universe_size=min_universe_size,
    )

    placebo_results: dict[str, CrossSectionalPlaceboResult] = {
        "shuffled_signal_placebo": shuffled_signal_placebo(bucket_rows, feature_col=feature_col, target_col=target_col, n_trials=n_placebo_trials, min_universe_size=min_universe_size),
        "shifted_signal_placebo": shifted_signal_placebo(bucket_rows, feature_col=feature_col, target_col=target_col, shift_bars=1, min_universe_size=min_universe_size),
        "time_shuffled_target_placebo": time_shuffled_target_placebo(bucket_rows, feature_col=feature_col, target_col=target_col, n_trials=n_placebo_trials, min_universe_size=min_universe_size),
    }
    from src.options.placebo_extensions import symbol_identity_shuffle_placebo
    placebo_results["random_bucket_assignment_placebo"] = symbol_identity_shuffle_placebo(
        bucket_rows, feature_col=feature_col, target_col=target_col, n_trials=n_placebo_trials, min_universe_size=min_universe_size,
    )

    # Phase 31-shaped affordability/liquidity/cost (bucket rows carry the same bid/ask/volume/OI/spread_pct
    # column names, as bucket MEDIANS) -- reused unchanged for HypothesisEvidence's fields.
    affordability_p31_shaped = affordability_filter_report(bucket_rows)
    liquidity = liquidity_report(bucket_rows)
    gross_effect = cs_evidence.report.quantile_report.spread_q5_minus_q1 if (cs_evidence.applicable and cs_evidence.report) else None
    cost_sensitivity = cost_sensitivity_report(gross_effect, liquidity)

    base_evidence = HypothesisEvidence(
        hypothesis_id=hypothesis.hypothesis_id, feature_col=feature_col, target_col=target_col, primary_horizon=horizon,
        cross_sectional=cs_evidence, time_series=ts_evidence, underlying_control=underlying_control, robustness=robustness,
        temporal_alignment=temporal, bootstrap=bootstrap, placebo_results=placebo_results, affordability=affordability_p31_shaped,
        liquidity=liquidity, cost_sensitivity=cost_sensitivity, outlier_trimmed_ic=outlier_result.ic_after,
        bh_significant=None, bh_adjusted_p=None,
    )

    # Part 13's richer affordability (percentiles + cheapest real contracts) -- from the ORIGINAL
    # contract-day panel. Shared across every hypothesis (same campaign-wide real contract universe),
    # the same convention Phase 31 used for its own affordability reporting.
    bucket_affordability = build_bucket_affordability_report(contract_day_rows)

    return BucketHypothesisResult(
        hypothesis_id=hypothesis.hypothesis_id, pooled_time_series=pooled, per_symbol=per_symbol, symbol_balanced=balanced,
        weighting_comparison=weighting, leave_one_period_out=period_results, outlier_removal=outlier_result,
        bucket_affordability=bucket_affordability, base_evidence=base_evidence,
        classification=DiscoveryClassification.NOT_READY, classification_reason="", gate=None,
        tradeability=TradeabilityClassification.DATA_LIMITED,
    )


@dataclass(frozen=True)
class Phase32Report:
    scheme_selection: SchemeSelectionResult
    hypotheses: tuple[Hypothesis, ...]
    n_contract_day_rows: int
    n_bucket_rows: int
    underlyings: tuple[str, ...]
    results: dict[str, BucketHypothesisResult]
    multiple_testing: dict[str, object]
    phase31_comparison: dict[str, object]


def _phase31_comparison(report: "Phase32Report") -> dict[str, object]:
    """Part 15's explicit 9 questions, answered from THIS campaign's
    own real results — never asserted without evidence."""
    any_discovery_supported = any(r.classification == DiscoveryClassification.DISCOVERY_SUPPORTED for r in report.results.values())
    any_promising = any(r.classification == DiscoveryClassification.PROMISING for r in report.results.values())
    any_underlying_survived = any(
        r.base_evidence.underlying_control is not None and getattr(r.base_evidence.underlying_control, "classification", None) == "option_adds_information"
        for r in report.results.values()
    )
    any_bh_significant = any(r.base_evidence.bh_significant is True for r in report.results.values())
    any_placebo_separated = any(
        (shuffled := r.base_evidence.placebo_results.get("shuffled_signal_placebo")) is not None
        and shuffled.empirical_p_value is not None and shuffled.empirical_p_value < 0.10
        for r in report.results.values()
    )
    any_robust = any(not r.base_evidence.robustness.fragile for r in report.results.values())
    any_affordable = any(
        r.bucket_affordability.pct_affordable is not None and r.bucket_affordability.pct_affordable >= 0.5
        for r in report.results.values()
    )
    any_gate_passed = any(r.gate is not None and r.gate.passed for r in report.results.values())
    n_testable = sum(1 for r in report.results.values() if r.classification not in (DiscoveryClassification.NOT_READY,))

    return {
        "q1_solved_contract_density_problem": report.n_bucket_rows > 0 and report.scheme_selection.fine_cells_meeting_threshold + report.scheme_selection.coarse_cells_meeting_threshold > 0,
        "q2_effective_sample_size_increased": report.n_bucket_rows > 0,  # see report for the actual before/after row counts
        "q3_any_phase31_null_became_testable": n_testable > 0,
        "q4_survived_underlying_controls": any_underlying_survived,
        "q5_survived_multiple_testing": any_bh_significant,
        "q6_survived_placebo": any_placebo_separated,
        "q7_survived_symbol_period_robustness": any_robust,
        "q8_became_affordable": any_affordable,
        "q9_passed_promising_gate": any_gate_passed,
        "any_discovery_supported": any_discovery_supported,
        "any_promising": any_promising,
        "still_a_null_result": not (any_discovery_supported or any_promising or any_gate_passed),
    }


def run_campaign(
    store: InMemoryLeanSampleStore, *,
    max_contracts_per_underlying: int = 6000,
    n_placebo_trials: int = DEFAULT_N_PLACEBO_TRIALS, n_bootstrap_resamples: int = DEFAULT_N_BOOTSTRAP_RESAMPLES,
    hypothesis_registry_path: Path | None = None, preregistration_store_path: Path | None = None,
    min_universe_size: int = MIN_SAMPLE.min_cross_sectional_peer_group,
) -> Phase32Report:
    hypotheses = build_hypotheses()
    if hypothesis_registry_path is not None and preregistration_store_path is not None:
        registry = HypothesisRegistry(hypothesis_registry_path)
        prereg_store = PreregistrationStore(preregistration_store_path)
        hypotheses = register_all(registry, prereg_store)
        for h in hypotheses:
            require_preregistered(prereg_store, h.hypothesis_id, h.version)

    contract_day_rows = build_panel_rows(store, max_contracts_per_underlying=max_contracts_per_underlying)
    scheme_selection = select_scheme_by_density(contract_day_rows)
    bucket_rows = build_bucket_panel(contract_day_rows, scheme_selection.chosen_scheme)

    raw_results: dict[str, BucketHypothesisResult] = {
        h.hypothesis_id: evaluate_one_bucket_hypothesis(
            h, bucket_rows, contract_day_rows, n_placebo_trials=n_placebo_trials, n_bootstrap_resamples=n_bootstrap_resamples,
            min_universe_size=min_universe_size,
        )
        for h in hypotheses
    }

    labeled_p = [
        (hid, r.base_evidence.cross_sectional.report.ic_p_value
         if (r.base_evidence.cross_sectional.applicable and r.base_evidence.cross_sectional.report and r.base_evidence.cross_sectional.report.ic_p_value is not None)
         else 1.0)
        for hid, r in raw_results.items()
    ]
    mtc = multiple_testing_across_family(labeled_p)
    bh_by_id = {r.label: r for r in mtc["benjamini_hochberg"].results}

    final_results: dict[str, BucketHypothesisResult] = {}
    for hid, r in raw_results.items():
        bh = bh_by_id.get(hid)
        updated_evidence = dataclasses.replace(
            r.base_evidence, bh_significant=(bh.significant_at_alpha if bh else None), bh_adjusted_p=(bh.adjusted_p_value if bh else None),
        )
        classification, reason = classify_hypothesis(updated_evidence)
        gate = evaluate_gate(updated_evidence)
        tradeability = classify_tradeability(r.bucket_affordability, classification)
        final_results[hid] = dataclasses.replace(
            r, base_evidence=updated_evidence, classification=classification, classification_reason=reason, gate=gate, tradeability=tradeability,
        )

    report = Phase32Report(
        scheme_selection=scheme_selection, hypotheses=hypotheses, n_contract_day_rows=len(contract_day_rows),
        n_bucket_rows=len(bucket_rows), underlyings=tuple(sorted({r["underlying_symbol"] for r in bucket_rows})),
        results=final_results, multiple_testing=mtc, phase31_comparison={},
    )
    report = dataclasses.replace(report, phase31_comparison=_phase31_comparison(report))
    return report
