"""Phase 33, Parts C-L/24 — the P22-OPT-013 coarse-grained replication
campaign: ties together every `phase33_*` replication module plus
extensive reuse of Phase 31/32/33-Part-A machinery.

WHAT IS REUSED, UNCHANGED: `phase31_panel_builder.build_panel_rows`
(contract-day panel), `phase32_density_audit.select_scheme_by_density`
(bucket scheme selection -- Part E's "frozen before evaluation, no
post-hoc expansion"), `phase32_bucket_panel.build_bucket_panel` (causal
bucket construction + Phase 32's existing forward targets, including
`forward_bucket_mfe_5`/`forward_bucket_mae_5`/`forward_bucket_return_5`/
`forward_abs_bucket_return_5` -- ALL of Part D's targets except the
MFE-MAE spread already exist verbatim and are never redefined here),
`phase32_campaign.evaluate_one_bucket_hypothesis` (the FULL Phase 31/32
evidence stack: pooled time-series, cross-sectional, per-symbol,
symbol-balanced, underlying control, robustness stratification
[year/underlying/DTE-bucket/moneyness/call-put + leave-one-underlying-out],
temporal alignment, bootstrap, placebo battery, leave-one-period-out,
outlier removal, affordability/liquidity/cost -- called with the SAME
row schema Phase 32 used, since the replication's feature is merged
onto Phase 32's own bucket rows), `phase33_corrected_campaign.
register_hypothesis_tests`/`phase33_test_registry.apply_correction`
(the SAME repaired multiple-testing accounting Part A built -- Part I's
explicit "Every test from Part B/G must enter the corrected registry
from Part A"), and `phase31_classification.classify_hypothesis`/
`phase31_gate.evaluate_gate`/`phase32_affordability.classify_tradeability`
(the SAME 7-value classification and 12-criterion gate, never a weaker
custom category -- Part K's explicit instruction).

WHAT IS NEW (built for this phase specifically): `phase33_range_expansion_feature`
(Part C's bucket-level feature), `phase33_group_balanced_evidence` (Part
E's DTE/moneyness/call-put-balanced pooled relationships), and
`phase33_replication_robustness` (Part G's non-overlapping-window
re-evaluation and real expiration/year concentration -- neither
computable from anything that already existed, since Phase 32's bucket
rows discard real expiration identity and no prior module re-evaluated
a relationship on a systematically thinned, non-overlapping subsample).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.phase31_classification import DiscoveryClassification, classify_hypothesis
from src.options.phase31_gate import GateResult, evaluate_gate
from src.options.phase31_panel_builder import build_panel_rows
from src.options.phase32_affordability import TradeabilityClassification, classify_tradeability
from src.options.phase32_bucket_panel import build_bucket_panel
from src.options.phase32_campaign import BucketHypothesisResult, evaluate_one_bucket_hypothesis
from src.options.phase32_density_audit import SchemeSelectionResult, select_scheme_by_density
from src.options.phase32_hypotheses import MIN_SAMPLE
from src.options.phase33_group_balanced_evidence import GroupBalancedResult, group_balanced_pooled_relationship, group_relationships
from src.options.phase33_range_expansion_feature import attach_range_expansion_features
from src.options.phase33_replication_hypotheses import FEATURE_COL, IS_PRIMARY_BY_ID, PRIMARY_HYPOTHESIS_ID, build_hypotheses, register_all
from src.options.phase33_replication_robustness import (
    ConcentrationReport,
    NonOverlapResult,
    evaluate_non_overlap,
    expiration_concentration,
    year_concentration,
)
from src.options.phase33_corrected_campaign import register_hypothesis_tests
from src.options.phase33_test_registry import (
    DIAGNOSTIC_FAMILY,
    PLACEBO_FAMILY,
    PRIMARY_FAMILY,
    CorrectionResult,
    InferentialTestRecord,
    TestRegistry,
    apply_correction,
)
from src.research.hypothesis import Hypothesis, HypothesisRegistry
from src.research.preregistration import PreregistrationStore, require_preregistered

DEFAULT_N_PLACEBO_TRIALS = 25
DEFAULT_N_BOOTSTRAP_RESAMPLES = 100
DOMINANCE_THRESHOLD = 0.60  # Part G: "does not depend primarily on one X" -- same 60% convention as Phase 32's symbol-balanced dominance flag
NON_OVERLAP_IC_RETENTION_FLOOR = 0.5  # Phase 23 Part 9's own finding: the point estimate survived at ~88% of its original size; a >=50% retention is the same "weakened but not destroyed" standard, not a new bar invented here


def _mfe_minus_mae(rows: list[dict], horizon: int = 5) -> list[dict]:
    """Part D's Target H analogue (`mfe_5 - mae_5`, mirroring Phase
    23's own spread-based target) -- the only target NOT already present
    verbatim in Phase 32's bucket panel, so it is derived here, once,
    from the two targets that already are (`forward_bucket_mfe_h`/
    `forward_bucket_mae_h`), never a new independent computation."""
    mfe_col, mae_col, out_col = f"forward_bucket_mfe_{horizon}", f"forward_bucket_mae_{horizon}", f"bucket_mfe_minus_mae_{horizon}"
    out = []
    for r in rows:
        new_row = dict(r)
        mfe, mae = r.get(mfe_col), r.get(mae_col)
        new_row[out_col] = (mfe - mae) if (mfe is not None and mae is not None) else None
        out.append(new_row)
    return out


@dataclass(frozen=True)
class ReplicationHypothesisResult:
    hypothesis_id: str
    is_primary: bool
    base_result: BucketHypothesisResult  # the FULL Phase 31/32 evidence stack, reused unchanged
    classification: DiscoveryClassification
    classification_reason: str
    gate: GateResult
    tradeability: TradeabilityClassification
    dte_balanced: GroupBalancedResult
    moneyness_balanced: GroupBalancedResult
    call_put_balanced: GroupBalancedResult
    non_overlap: NonOverlapResult


def evaluate_replication_hypothesis(
    hypothesis: Hypothesis, bucket_rows: Sequence[dict], contract_day_rows: Sequence[dict], *,
    n_placebo_trials: int = DEFAULT_N_PLACEBO_TRIALS, n_bootstrap_resamples: int = DEFAULT_N_BOOTSTRAP_RESAMPLES,
    min_universe_size: int = MIN_SAMPLE.min_cross_sectional_peer_group,
) -> BucketHypothesisResult:
    """Reuses `phase32_campaign.evaluate_one_bucket_hypothesis` COMPLETELY
    UNCHANGED -- it already computes everything Part E (pooled/cross-
    sectional/per-symbol/symbol-balanced), Part F (underlying control),
    and most of Part G (robustness stratification by year/underlying/
    DTE-bucket/moneyness/call-put, leave-one-underlying-out,
    leave-one-period-out, outlier removal, placebo battery) need, since
    the replication feature was merged onto rows sharing Phase 32's
    exact schema."""
    return evaluate_one_bucket_hypothesis(
        hypothesis, bucket_rows, contract_day_rows, n_placebo_trials=n_placebo_trials,
        n_bootstrap_resamples=n_bootstrap_resamples, min_universe_size=min_universe_size,
    )


@dataclass(frozen=True)
class ReplicationVerdict:
    """Part N's mandatory explicit answers, computed ONLY from the
    PRIMARY hypothesis's (`P33-REPL-MFE`) finalized evidence -- never
    from a secondary target, so a positive MAE/ABS/DIR result could
    never be used to claim the parent relationship "replicated.\""""

    did_replicate: bool
    survived_underlying_control: bool
    survived_multiple_testing: bool
    survived_outlier_removal: bool
    survived_non_overlap: bool
    survived_concentration: bool
    is_directional: bool
    is_economically_tradeable: bool
    passes_promising_gate: bool
    reason: str


def _compute_verdict(
    primary: ReplicationHypothesisResult, directional: ReplicationHypothesisResult,
    expiration_conc: ConcentrationReport, year_conc: ConcentrationReport,
) -> ReplicationVerdict:
    ev = primary.base_result.base_evidence
    survived_underlying = (
        ev.underlying_control is not None
        and getattr(ev.underlying_control, "classification", None) == "option_adds_information"
    )
    survived_mtc = ev.bh_significant is True
    survived_outliers = not primary.base_result.outlier_removal.outlier_dependent
    non_overlap = primary.non_overlap
    ic_before, ic_after = non_overlap.cross_sectional_before_ic, non_overlap.cross_sectional_after_ic
    survived_non_overlap = (
        ic_before is not None and ic_after is not None and abs(ic_before) > 0
        and (ic_after / ic_before) >= NON_OVERLAP_IC_RETENTION_FLOOR
        and (non_overlap.cross_sectional_after_p is None or non_overlap.cross_sectional_after_p < 0.10)
    )
    not_symbol_dominated = not ev.robustness.sign_flips_across_underlyings
    not_expiration_dominated = expiration_conc.top_share is None or expiration_conc.top_share < DOMINANCE_THRESHOLD
    not_year_dominated = year_conc.top_share is None or year_conc.top_share < DOMINANCE_THRESHOLD
    survived_concentration = not_symbol_dominated and not_expiration_dominated and not_year_dominated and not primary.base_result.symbol_balanced.dominated_by_single_symbol

    is_directional = directional.classification in (DiscoveryClassification.DISCOVERY_SUPPORTED, DiscoveryClassification.PROMISING)
    is_tradeable = primary.tradeability == TradeabilityClassification.TRADEABLE
    passes_gate = primary.gate.passed
    did_replicate = primary.classification in (DiscoveryClassification.DISCOVERY_SUPPORTED, DiscoveryClassification.PROMISING)

    reason = (
        f"Primary hypothesis {primary.hypothesis_id} classified {primary.classification.value.upper()}. "
        f"underlying_control_survived={survived_underlying}, multiple_testing_survived={survived_mtc}, "
        f"outlier_removal_survived={survived_outliers}, non_overlap_survived={survived_non_overlap}, "
        f"concentration_survived={survived_concentration}, directional_finding={is_directional}, "
        f"economically_tradeable={is_tradeable}, gate_passed={passes_gate}."
    )
    return ReplicationVerdict(
        did_replicate=did_replicate, survived_underlying_control=survived_underlying, survived_multiple_testing=survived_mtc,
        survived_outlier_removal=survived_outliers, survived_non_overlap=survived_non_overlap, survived_concentration=survived_concentration,
        is_directional=is_directional, is_economically_tradeable=is_tradeable, passes_promising_gate=passes_gate, reason=reason,
    )


@dataclass(frozen=True)
class ReplicationReport:
    scheme_selection: SchemeSelectionResult
    hypotheses: tuple[Hypothesis, ...]
    n_contract_day_rows: int
    n_bucket_rows: int
    n_rows_with_range_expansion: int
    registry: TestRegistry
    primary_correction: CorrectionResult
    placebo_correction: CorrectionResult
    results: dict[str, ReplicationHypothesisResult]
    expiration_concentration: ConcentrationReport
    year_concentration: ConcentrationReport
    verdict: ReplicationVerdict


def run_replication_campaign(
    store: InMemoryLeanSampleStore, *,
    max_contracts_per_underlying: int = 6000,
    n_placebo_trials: int = DEFAULT_N_PLACEBO_TRIALS, n_bootstrap_resamples: int = DEFAULT_N_BOOTSTRAP_RESAMPLES,
    hypothesis_registry_path: Path | None = None, preregistration_store_path: Path | None = None,
    min_universe_size: int = MIN_SAMPLE.min_cross_sectional_peer_group,
) -> ReplicationReport:
    hypotheses = build_hypotheses()
    if hypothesis_registry_path is not None and preregistration_store_path is not None:
        registry_store = HypothesisRegistry(hypothesis_registry_path)
        prereg_store = PreregistrationStore(preregistration_store_path)
        hypotheses = register_all(registry_store, prereg_store)
        for h in hypotheses:
            require_preregistered(prereg_store, h.hypothesis_id, h.version)

    # --- Part C/E: contract-day panel -> frozen Phase 32 bucket scheme -> bucket panel -> range-expansion feature ---
    contract_day_rows = build_panel_rows(store, max_contracts_per_underlying=max_contracts_per_underlying)
    scheme_selection = select_scheme_by_density(contract_day_rows)
    bucket_rows = build_bucket_panel(contract_day_rows, scheme_selection.chosen_scheme)
    bucket_rows = attach_range_expansion_features(bucket_rows, contract_day_rows, scheme_selection.chosen_scheme)
    bucket_rows = _mfe_minus_mae(bucket_rows, horizon=5)
    n_with_feature = sum(1 for r in bucket_rows if r.get(FEATURE_COL) is not None)

    test_registry = TestRegistry()
    raw_results: dict[str, ReplicationHypothesisResult] = {}
    for h in hypotheses:
        base = evaluate_replication_hypothesis(
            h, bucket_rows, contract_day_rows, n_placebo_trials=n_placebo_trials,
            n_bootstrap_resamples=n_bootstrap_resamples, min_universe_size=min_universe_size,
        )
        register_hypothesis_tests(test_registry, h, base, bucket_definition=scheme_selection.chosen_scheme.name)

        # --- Part E: DTE-balanced / moneyness-balanced / call-put-balanced ---
        dte_groups = group_relationships(bucket_rows, feature_col=h.required_features[0], target_col=h.target_definition, key_fn=lambda r: r["dte_bucket"], group_label="dte_bucket")
        money_groups = group_relationships(bucket_rows, feature_col=h.required_features[0], target_col=h.target_definition, key_fn=lambda r: r["moneyness_bucket"], group_label="moneyness_bucket")
        cp_groups = group_relationships(bucket_rows, feature_col=h.required_features[0], target_col=h.target_definition, key_fn=lambda r: r["call_put"], group_label="call_put")
        dte_balanced = group_balanced_pooled_relationship(dte_groups, dominance_threshold=DOMINANCE_THRESHOLD)
        money_balanced = group_balanced_pooled_relationship(money_groups, dominance_threshold=DOMINANCE_THRESHOLD)
        cp_balanced = group_balanced_pooled_relationship(cp_groups, dominance_threshold=DOMINANCE_THRESHOLD)
        for label, balanced in (("dte_balanced", dte_balanced), ("moneyness_balanced", money_balanced), ("call_put_balanced", cp_balanced)):
            test_registry.register_or_replace(_group_balanced_record(h, balanced, label, bucket_definition=scheme_selection.chosen_scheme.name))

        # --- Part G: non-overlapping-window re-evaluation ---
        non_overlap = evaluate_non_overlap(bucket_rows, feature_col=h.required_features[0], target_col=h.target_definition, horizon=h.prediction_horizon_bars, min_universe_size=min_universe_size)
        test_registry.register_or_replace(_non_overlap_record(h, non_overlap, bucket_definition=scheme_selection.chosen_scheme.name))

        raw_results[h.hypothesis_id] = ReplicationHypothesisResult(
            hypothesis_id=h.hypothesis_id, is_primary=IS_PRIMARY_BY_ID[h.hypothesis_id], base_result=base,
            classification=DiscoveryClassification.NOT_READY, classification_reason="", gate=None,
            tradeability=TradeabilityClassification.DATA_LIMITED, dte_balanced=dte_balanced, moneyness_balanced=money_balanced,
            call_put_balanced=cp_balanced, non_overlap=non_overlap,
        )

    primary_correction = apply_correction(test_registry, PRIMARY_FAMILY)
    placebo_correction = apply_correction(test_registry, PLACEBO_FAMILY)

    final_results: dict[str, ReplicationHypothesisResult] = {}
    for h in hypotheses:
        r = raw_results[h.hypothesis_id]
        bh_significant, bh_p = _cross_sectional_status(test_registry, h.hypothesis_id)
        updated_evidence = dataclasses.replace(r.base_result.base_evidence, bh_significant=bh_significant, bh_adjusted_p=bh_p)
        classification, reason = classify_hypothesis(updated_evidence)
        gate = evaluate_gate(updated_evidence)
        tradeability = classify_tradeability(r.base_result.bucket_affordability, classification)
        updated_base = dataclasses.replace(r.base_result, base_evidence=updated_evidence)
        final_results[h.hypothesis_id] = dataclasses.replace(r, base_result=updated_base, classification=classification, classification_reason=reason, gate=gate, tradeability=tradeability)

    expiration_conc = expiration_concentration(contract_day_rows)
    year_conc = year_concentration(contract_day_rows)
    verdict = _compute_verdict(final_results[PRIMARY_HYPOTHESIS_ID], final_results[hypothesis_id_for("DIR")], expiration_conc, year_conc)

    return ReplicationReport(
        scheme_selection=scheme_selection, hypotheses=hypotheses, n_contract_day_rows=len(contract_day_rows),
        n_bucket_rows=len(bucket_rows), n_rows_with_range_expansion=n_with_feature, registry=test_registry,
        primary_correction=primary_correction, placebo_correction=placebo_correction, results=final_results,
        expiration_concentration=expiration_conc, year_concentration=year_conc, verdict=verdict,
    )


def hypothesis_id_for(suffix: str) -> str:
    return f"P33-REPL-{suffix}"


def _cross_sectional_status(registry: TestRegistry, hypothesis_id: str) -> tuple[bool | None, float | None]:
    """The SAME resolution rule `phase33_corrected_campaign._cross_sectional_status`
    uses -- duplicated here rather than imported (it is a tiny, private,
    registry-lookup helper, not shared domain logic) to keep each
    campaign module self-contained."""
    for record in registry.by_hypothesis(hypothesis_id):
        if record.aggregation_method == "cross_sectional":
            if record.correction_status == "SIGNIFICANT_AFTER_BH":
                return True, record.p_value
            if record.correction_status == "NOT_SIGNIFICANT_AFTER_BH":
                return False, record.p_value
            return None, record.p_value
    return None, None


def _group_balanced_record(hypothesis: Hypothesis, balanced: GroupBalancedResult, aggregation_method: str, *, bucket_definition: str) -> InferentialTestRecord:
    return InferentialTestRecord(
        hypothesis_id=hypothesis.hypothesis_id, feature_family="P22-OPT-013-REPLICATION", feature=hypothesis.required_features[0],
        target=hypothesis.target_definition, horizon=hypothesis.prediction_horizon_bars, aggregation_method=aggregation_method,
        bucket_definition=bucket_definition, underlying="ALL", test_type="mean_of_per_group_correlations",
        sample_size=balanced.n_groups_eligible, p_value=None, effect_size=balanced.group_balanced_spearman, correction_family=DIAGNOSTIC_FAMILY,
    )


def _non_overlap_record(hypothesis: Hypothesis, non_overlap: NonOverlapResult, *, bucket_definition: str) -> InferentialTestRecord:
    return InferentialTestRecord(
        hypothesis_id=hypothesis.hypothesis_id, feature_family="P22-OPT-013-REPLICATION", feature=hypothesis.required_features[0],
        target=hypothesis.target_definition, horizon=hypothesis.prediction_horizon_bars, aggregation_method="non_overlapping_window",
        bucket_definition=bucket_definition, underlying="ALL", test_type="cross_sectional_ic_p_value_after_thinning",
        sample_size=non_overlap.n_rows_after, p_value=non_overlap.cross_sectional_after_p, effect_size=non_overlap.cross_sectional_after_ic,
        correction_family=DIAGNOSTIC_FAMILY,
    )
