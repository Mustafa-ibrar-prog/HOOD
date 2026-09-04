"""Phase 33, Part A/24 — the corrected campaign runner.

Reuses `phase32_campaign.evaluate_one_bucket_hypothesis` UNMODIFIED for
every hypothesis's raw evidence (cross-sectional, pooled time-series,
per-symbol, symbol-balanced, robustness, placebos — nothing about HOW
those are computed changes this phase). What changes is what happens
AFTER: instead of `phase32_campaign.run_campaign`'s narrow
cross-sectional-only `multiple_testing_across_family(labeled_p)` call,
`run_corrected_campaign` builds the COMPLETE `phase33_test_registry.
TestRegistry` this phase's audit found missing (every cross-sectional,
pooled, and per-symbol test — real, formal p-values from `correlation_p_value`
— entered under `PRIMARY_FAMILY`; symbol-balanced/leave-one-out under
`DIAGNOSTIC_FAMILY`; every placebo's empirical p-value under
`PLACEBO_FAMILY`), runs `apply_correction` ONCE across the properly-sized
family, and re-derives each hypothesis's `bh_significant`/`bh_adjusted_p`
(and therefore its classification and gate result) from ITS
CROSS-SECTIONAL test's status within that LARGER, more complete family —
never from a newly-favorable p-value the old narrow family didn't have
(Part A: "Do not reinterpret previously non-significant findings merely
because the correction implementation changed"). A larger, more complete
family can only make the Benjamini-Hochberg threshold equal or more
conservative for any individual test, never less — so this fix can only
ever REMOVE a false claim of significance, never manufacture a new one.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.phase31_classification import DiscoveryClassification, classify_hypothesis
from src.options.phase31_gate import evaluate_gate
from src.options.phase31_panel_builder import build_panel_rows
from src.options.phase32_affordability import classify_tradeability
from src.options.phase32_bucket_panel import build_bucket_panel
from src.options.phase32_campaign import BucketHypothesisResult, evaluate_one_bucket_hypothesis
from src.options.phase32_density_audit import SchemeSelectionResult, select_scheme_by_density
from src.options.phase32_hypotheses import FEATURE_FAMILY_BY_ID, MIN_SAMPLE, build_hypotheses, register_all
from src.options.phase33_test_registry import (
    DIAGNOSTIC_FAMILY,
    PLACEBO_FAMILY,
    PRIMARY_FAMILY,
    CorrectionResult,
    InferentialTestRecord,
    TestRegistry,
    apply_correction,
    correlation_p_value,
)
from src.research.hypothesis import Hypothesis, HypothesisRegistry
from src.research.preregistration import PreregistrationStore, require_preregistered

DEFAULT_N_PLACEBO_TRIALS = 25
DEFAULT_N_BOOTSTRAP_RESAMPLES = 100


def register_hypothesis_tests(
    registry: TestRegistry, hypothesis: Hypothesis, result: BucketHypothesisResult, *, bucket_definition: str,
) -> None:
    """The actual fix: every test `evaluate_one_bucket_hypothesis`
    already computed for this hypothesis is registered here, before any
    correction runs. Nothing is silently left out."""
    ev = result.base_evidence
    feature, target, horizon = ev.feature_col, ev.target_col, ev.primary_horizon
    family_letter = FEATURE_FAMILY_BY_ID.get(hypothesis.hypothesis_id, "?")

    # --- cross-sectional (already had a formal p-value in Phase 32) ---
    cs = ev.cross_sectional
    cs_p = cs.report.ic_p_value if (cs.applicable and cs.report) else None
    cs_n = sum(1 for p in cs.report.ic_summary.points if p.ic is not None) if (cs.applicable and cs.report) else 0
    cs_effect = cs.report.ic_summary.average_ic if (cs.applicable and cs.report) else None
    registry.register(InferentialTestRecord(
        hypothesis_id=hypothesis.hypothesis_id, feature_family=family_letter, feature=feature, target=target, horizon=horizon,
        aggregation_method="cross_sectional", bucket_definition=bucket_definition, underlying="ALL",
        test_type="cross_sectional_ic_p_value", sample_size=cs_n, p_value=cs_p, effect_size=cs_effect,
        correction_family=PRIMARY_FAMILY,
    ))

    # --- pooled time-series (Phase 32's gap: never registered before) ---
    pooled = result.pooled_time_series
    pooled_p = correlation_p_value(pooled.spearman_correlation, pooled.sample_count) if pooled else None
    registry.register(InferentialTestRecord(
        hypothesis_id=hypothesis.hypothesis_id, feature_family=family_letter, feature=feature, target=target, horizon=horizon,
        aggregation_method="pooled_time_series", bucket_definition=bucket_definition, underlying="ALL",
        test_type="spearman_correlation_p_value", sample_size=(pooled.sample_count if pooled else 0),
        p_value=pooled_p, effect_size=(pooled.spearman_correlation if pooled else None),
        correction_family=PRIMARY_FAMILY,
    ))

    # --- per-symbol (Phase 32's gap: never registered before -- one test PER underlying) ---
    for p in result.per_symbol:
        p_value = correlation_p_value(p.result.spearman_correlation, p.n_observations) if p.result else None
        registry.register(InferentialTestRecord(
            hypothesis_id=hypothesis.hypothesis_id, feature_family=family_letter, feature=feature, target=target, horizon=horizon,
            aggregation_method="per_symbol", bucket_definition=bucket_definition, underlying=p.underlying,
            test_type="spearman_correlation_p_value", sample_size=p.n_observations, p_value=p_value,
            effect_size=(p.result.spearman_correlation if p.result else None), correction_family=PRIMARY_FAMILY,
        ))

    # --- symbol-balanced (an average of correlations -- no well-defined p-value; DIAGNOSTIC, not silently omitted) ---
    registry.register(InferentialTestRecord(
        hypothesis_id=hypothesis.hypothesis_id, feature_family=family_letter, feature=feature, target=target, horizon=horizon,
        aggregation_method="symbol_balanced", bucket_definition=bucket_definition, underlying="ALL",
        test_type="mean_of_per_symbol_correlations", sample_size=result.symbol_balanced.n_symbols_eligible,
        p_value=None, effect_size=result.symbol_balanced.symbol_balanced_spearman, correction_family=DIAGNOSTIC_FAMILY,
    ))

    # --- leave-one-underlying-out (Phase 31's robustness reuse) -- descriptive point estimates, DIAGNOSTIC ---
    for stratum in ev.robustness.leave_one_underlying_out:
        registry.register(InferentialTestRecord(
            hypothesis_id=hypothesis.hypothesis_id, feature_family=family_letter, feature=feature, target=target, horizon=horizon,
            aggregation_method="leave_one_symbol_out", bucket_definition=bucket_definition, underlying=stratum.stratum_value,
            test_type="cross_sectional_ic_point_estimate", sample_size=stratum.n_rows, p_value=None,
            effect_size=stratum.average_ic, correction_family=DIAGNOSTIC_FAMILY,
        ))

    # --- leave-one-period-out (one record per period -- the period label is folded into
    # aggregation_method, same convention as the placebo methods below, since the registry's
    # identity key is (hypothesis_id, aggregation_method, underlying, target) and every period
    # here shares underlying="ALL") ---
    for period in result.leave_one_period_out:
        registry.register(InferentialTestRecord(
            hypothesis_id=hypothesis.hypothesis_id, feature_family=family_letter, feature=feature, target=target, horizon=horizon,
            aggregation_method=f"leave_one_period_out:{period.period_label}", bucket_definition=bucket_definition, underlying="ALL",
            test_type="pooled_spearman_point_estimate", sample_size=period.n_observations, p_value=None,
            effect_size=period.spearman_correlation, correction_family=DIAGNOSTIC_FAMILY,
        ))

    # --- placebos (real empirical p-values -- a genuinely different statistical question, own family) ---
    for method_name, placebo in ev.placebo_results.items():
        registry.register(InferentialTestRecord(
            hypothesis_id=hypothesis.hypothesis_id, feature_family=family_letter, feature=feature, target=target, horizon=horizon,
            aggregation_method=f"placebo:{method_name}", bucket_definition=bucket_definition, underlying="ALL",
            test_type="placebo_empirical_p_value", sample_size=placebo.n_trials, p_value=placebo.empirical_p_value,
            effect_size=placebo.observed_statistic, correction_family=PLACEBO_FAMILY,
        ))


@dataclass(frozen=True)
class CorrectedPhase32Report:
    scheme_selection: SchemeSelectionResult
    hypotheses: tuple[Hypothesis, ...]
    n_contract_day_rows: int
    n_bucket_rows: int
    registry: TestRegistry
    primary_correction: CorrectionResult
    placebo_correction: CorrectionResult
    results: dict[str, BucketHypothesisResult]  # re-derived classification/gate/tradeability, using the corrected status
    changed_conclusions: dict[str, str]  # hypothesis_id -> explanation, ONLY populated if a classification actually changed


def _cross_sectional_status(registry: TestRegistry, hypothesis_id: str) -> tuple[bool | None, float | None]:
    for record in registry.by_hypothesis(hypothesis_id):
        if record.aggregation_method == "cross_sectional":
            if record.correction_status == "SIGNIFICANT_AFTER_BH":
                return True, record.p_value
            if record.correction_status == "NOT_SIGNIFICANT_AFTER_BH":
                return False, record.p_value
            return None, record.p_value
    return None, None


def run_corrected_campaign(
    store: InMemoryLeanSampleStore, *,
    max_contracts_per_underlying: int = 6000,
    n_placebo_trials: int = DEFAULT_N_PLACEBO_TRIALS, n_bootstrap_resamples: int = DEFAULT_N_BOOTSTRAP_RESAMPLES,
    hypothesis_registry_path: Path | None = None, preregistration_store_path: Path | None = None,
    min_universe_size: int = MIN_SAMPLE.min_cross_sectional_peer_group,
    previous_results: dict[str, BucketHypothesisResult] | None = None,
) -> CorrectedPhase32Report:
    hypotheses = build_hypotheses()
    if hypothesis_registry_path is not None and preregistration_store_path is not None:
        registry_store = HypothesisRegistry(hypothesis_registry_path)
        prereg_store = PreregistrationStore(preregistration_store_path)
        hypotheses = register_all(registry_store, prereg_store)
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

    test_registry = TestRegistry()
    for h in hypotheses:
        register_hypothesis_tests(test_registry, h, raw_results[h.hypothesis_id], bucket_definition=scheme_selection.chosen_scheme.name)

    primary_correction = apply_correction(test_registry, PRIMARY_FAMILY)
    placebo_correction = apply_correction(test_registry, PLACEBO_FAMILY)

    final_results: dict[str, BucketHypothesisResult] = {}
    changed: dict[str, str] = {}
    for h in hypotheses:
        hid = h.hypothesis_id
        r = raw_results[hid]
        bh_significant, bh_p = _cross_sectional_status(test_registry, hid)
        updated_evidence = dataclasses.replace(r.base_evidence, bh_significant=bh_significant, bh_adjusted_p=bh_p)
        classification, reason = classify_hypothesis(updated_evidence)
        gate = evaluate_gate(updated_evidence)
        tradeability = classify_tradeability(r.bucket_affordability, classification)
        final_results[hid] = dataclasses.replace(
            r, base_evidence=updated_evidence, classification=classification, classification_reason=reason, gate=gate, tradeability=tradeability,
        )
        if previous_results is not None and hid in previous_results:
            old_classification = previous_results[hid].classification
            if old_classification != classification:
                changed[hid] = (
                    f"classification changed from {old_classification.value} to {classification.value} after "
                    f"correcting against the complete test family ({primary_correction.n_with_p_value} tests, "
                    f"was previously corrected against only the cross-sectional test per hypothesis)."
                )

    return CorrectedPhase32Report(
        scheme_selection=scheme_selection, hypotheses=hypotheses, n_contract_day_rows=len(contract_day_rows),
        n_bucket_rows=len(bucket_rows), registry=test_registry, primary_correction=primary_correction,
        placebo_correction=placebo_correction, results=final_results, changed_conclusions=changed,
    )
