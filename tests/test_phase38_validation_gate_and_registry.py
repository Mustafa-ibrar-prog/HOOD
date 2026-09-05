"""Phase 38, Part 13-14 — the formal validation gate and Phase 36
registry integration."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.options.phase33_test_registry import PRIMARY_FAMILY, TestRegistry, apply_correction
from src.options.phase38_affordability import ThousandDollarAffordabilityResult
from src.options.phase38_chronological_split import ChronologicalSplit
from src.options.phase38_economic_validation import EconomicValidationReport
from src.options.phase38_falsification import CostStressResult, PlaceboResult, TimingRobustnessResult
from src.options.phase38_registry_integration import GateNotPassedError, promote_if_validated
from src.options.phase38_test_registry_wiring import register_edge_result
from src.options.phase38_underlying_vs_option_edge import EdgeClassification, UnderlyingVsOptionEdgeResult
from src.options.phase38_validation_gate import GateEvidence, evaluate_validation_gate
from src.production.registry import StrategyMetadata, StrategyRegistry, StrategyStatus
from src.production.validation_artifact import ValidationArtifactStore


def _empty_edge(n=0, classification=EdgeClassification.INSUFFICIENT_SAMPLE):
    return UnderlyingVsOptionEdgeResult(n, None, None, None, None, classification, "x")


def _empty_economic_report(n=0):
    return EconomicValidationReport(n, None, None, None, None, None, None, None, None, None, None, None, None)


def _empty_affordability():
    from src.options.phase31_affordability_liquidity import AffordabilityFilterReport
    report = AffordabilityFilterReport(0, 0, None, None, None, None, None, 1000.0, None, None)
    return ThousandDollarAffordabilityResult(report, "ACCOUNT_FEASIBILITY_UNKNOWN_NO_PRICED_ROWS", None, None, None)


def _minimal_insufficient_evidence() -> GateEvidence:
    return GateEvidence(
        chronological_split=ChronologicalSplit((), (), (), False, "insufficient"),
        development_edge=_empty_edge(), validation_edge=_empty_edge(), holdout_edge=_empty_edge(),
        holdout_touched_before_freeze=False, test_registry=TestRegistry(), economic_report=_empty_economic_report(),
        spread_stress_results=(), cost_stress_results=(), leave_one_period_out={}, leave_one_symbol_out={},
        placebo_result=PlaceboResult("randomized_signal_placebo", 0, 0, None, None, "INSUFFICIENT_SAMPLE"),
        timing_robustness_result=TimingRobustnessResult("shifted_signal", 0, 0, None, None, "INSUFFICIENT_SAMPLE"),
        affordability=_empty_affordability(), data_quality=None,
    )


def _full_passing_evidence() -> GateEvidence:
    """A SYNTHETIC, test-only evidence bundle where every condition is
    satisfied -- proves the gate/registry plumbing works end to end.
    Never presented as real evidence for any real strategy."""
    registry = TestRegistry()
    edge = UnderlyingVsOptionEdgeResult(50, 0.10, 0.02, 0.08, 0.001, EdgeClassification.OPTION_ADDS_VALUE, "positive, significant")
    register_edge_result(registry, edge, horizon_label="5min")
    apply_correction(registry, PRIMARY_FAMILY)

    from src.options.phase38_falsification import OutcomeStats

    period_stats = {"2026-01": OutcomeStats(25, 0.05, 0.05, 0.6, 0.01), "2026-02": OutcomeStats(25, 0.06, 0.06, 0.6, 0.01)}
    symbol_stats = {"AAPL": OutcomeStats(25, 0.05, 0.05, 0.6, 0.01), "MSFT": OutcomeStats(25, 0.06, 0.06, 0.6, 0.01)}

    from src.options.phase31_affordability_liquidity import AffordabilityFilterReport

    affordability = ThousandDollarAffordabilityResult(
        AffordabilityFilterReport(50, 50, 100.0, 100.0, 50.0, 150.0, 1.0, 1000.0, 5.0, 100.0),
        "ACCOUNT_FEASIBILITY_HIGH", 10, 100.0, 1000.0,
    )

    return GateEvidence(
        chronological_split=ChronologicalSplit(tuple(range(30)), tuple(range(15)), tuple(range(15)), True, "30/15/15"),
        development_edge=edge, validation_edge=edge, holdout_edge=edge, holdout_touched_before_freeze=False,
        test_registry=registry, economic_report=EconomicValidationReport(50, 0.05, 0.05, 0.05, 0.6, 1.5, 1.8, 0.1, 0.05, 0.5, 0.3, 2.0, 30.0),
        spread_stress_results=(CostStressResult(1.0, 50, 0.04, True), CostStressResult(5.0, 50, 0.01, True)),
        cost_stress_results=(CostStressResult(1.0, 50, 0.04, True), CostStressResult(5.0, 50, 0.01, True)),
        leave_one_period_out=period_stats, leave_one_symbol_out=symbol_stats,
        placebo_result=PlaceboResult("randomized_signal_placebo", 50, 30, 0.05, 0.02, "OBSERVED_EXCEEDS_PLACEBO"),
        timing_robustness_result=TimingRobustnessResult("shifted_signal", 50, 50, 0.05, 0.04, "ROBUST_TO_SIGNAL_SHIFT"),
        affordability=affordability, data_quality=_clean_data_quality_report(),
    )


def _clean_data_quality_report():
    from src.research_recorder.quality_report import DataQualityReport

    return DataQualityReport(
        cycles_attempted=50, cycles_successful=50, cycles_failed=0, symbols_attempted=50, symbols_successful=50,
        option_contracts_observed=200, unique_option_contracts=50, unique_expirations=3, calls=200, puts=0,
        dte_distribution={"MEDIUM_16_45": 200}, moneyness_distribution={"NEAR_ATM": 200},
        quote_completeness_pct=1.0, stale_quote_count=0, duplicate_count=0, invalid_quote_count=0,
        api_failures=0, parser_failures=0,
    )


# --- Gate: the real, current state (insufficient evidence) --------------------------------------


def test_gate_fails_with_the_real_current_insufficient_evidence():
    """This is the REAL state of the project as of Phase 38 -- zero live
    observations recorded, so every downstream requirement is unmet."""
    result = evaluate_validation_gate(_minimal_insufficient_evidence())
    assert not result.passed
    assert "sufficient_sample_size" in result.unmet_condition_names


def test_gate_reports_every_unmet_condition_not_just_the_first():
    result = evaluate_validation_gate(_minimal_insufficient_evidence())
    assert len(result.unmet_condition_names) > 1


def test_gate_has_exactly_seventeen_conditions():
    result = evaluate_validation_gate(_minimal_insufficient_evidence())
    assert len(result.conditions) == 17
    assert [c.number for c in result.conditions] == list(range(1, 18))


# --- Gate: the synthetic all-pass fixture (never real) --------------------------------------------


def test_gate_passes_with_a_fully_satisfying_synthetic_evidence_bundle():
    result = evaluate_validation_gate(_full_passing_evidence())
    assert result.passed
    assert result.unmet_condition_names == ()


def test_gate_refuses_if_holdout_was_touched_before_freeze():
    evidence = _full_passing_evidence()
    import dataclasses
    tainted = dataclasses.replace(evidence, holdout_touched_before_freeze=True)
    result = evaluate_validation_gate(tainted)
    assert not result.passed
    assert "untouched_final_holdout" in result.unmet_condition_names


def test_gate_refuses_if_falsification_shows_placebo_indistinguishable():
    import dataclasses
    evidence = _full_passing_evidence()
    bad_placebo = PlaceboResult("randomized_signal_placebo", 50, 30, 0.05, 0.5, "OBSERVED_NOT_DISTINGUISHABLE_FROM_PLACEBO")
    tainted = dataclasses.replace(evidence, placebo_result=bad_placebo)
    result = evaluate_validation_gate(tainted)
    assert not result.passed
    assert "falsification_tests_passed" in result.unmet_condition_names


def test_gate_refuses_if_edge_is_underlying_derived():
    import dataclasses
    evidence = _full_passing_evidence()
    underlying_derived = UnderlyingVsOptionEdgeResult(50, 0.05, 0.05, 0.0, 0.9, EdgeClassification.UNDERLYING_DERIVED, "no excess")
    tainted = dataclasses.replace(evidence, holdout_edge=underlying_derived)
    result = evaluate_validation_gate(tainted)
    assert not result.passed
    assert "option_level_implementation_edge_demonstrated" in result.unmet_condition_names


# --- Registry integration ---------------------------------------------------------------------


def test_promote_if_validated_refuses_when_gate_not_passed(tmp_path):
    registry = StrategyRegistry(ValidationArtifactStore(tmp_path / "artifacts.jsonl"))
    registry.register(StrategyMetadata(
        strategy_id="TEST-STRAT", version="1.0", status=StrategyStatus.RESEARCH, created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        validation_status="x", historical_evidence_status="x", live_data_compatibility_status="x",
        allowed_option_structures=(), parameter_specification="x", risk_profile="x", author_or_research_provenance="x",
    ))
    evidence = _minimal_insufficient_evidence()
    gate_result = evaluate_validation_gate(evidence)
    with pytest.raises(GateNotPassedError):
        promote_if_validated(
            registry=registry, artifact_store=registry._artifact_store, strategy_id="TEST-STRAT", strategy_version="1.0",
            strategy_content_hash="abc", evidence=evidence, gate_result=gate_result, approved_by="human:test",
        )
    assert registry.get("TEST-STRAT", "1.0").status == StrategyStatus.RESEARCH  # unchanged


def test_promote_if_validated_succeeds_with_a_synthetic_passing_gate(tmp_path):
    """Proves the plumbing works end to end -- NEVER used for a real
    strategy in this phase (the real MomentumBreakoutStrategy evidence
    fails the gate, see test_phase38_campaign.py)."""
    artifact_store = ValidationArtifactStore(tmp_path / "artifacts.jsonl")
    registry = StrategyRegistry(artifact_store)
    registry.register(StrategyMetadata(
        strategy_id="TEST-STRAT", version="1.0", status=StrategyStatus.RESEARCH, created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        validation_status="x", historical_evidence_status="x", live_data_compatibility_status="x",
        allowed_option_structures=(), parameter_specification="x", risk_profile="x", author_or_research_provenance="x",
    ))
    evidence = _full_passing_evidence()
    gate_result = evaluate_validation_gate(evidence)
    status = promote_if_validated(
        registry=registry, artifact_store=artifact_store, strategy_id="TEST-STRAT", strategy_version="1.0",
        strategy_content_hash="abc123", evidence=evidence, gate_result=gate_result, approved_by="human:test",
    )
    assert status == StrategyStatus.VALIDATED
    assert registry.get("TEST-STRAT", "1.0").status == StrategyStatus.VALIDATED
    assert artifact_store.get("TEST-STRAT", "1.0") is not None


def test_validation_artifact_is_immutable_once_approved(tmp_path):
    from src.options.phase38_registry_integration import build_validation_artifact
    from src.production.validation_artifact import ValidationArtifactImmutabilityError

    evidence = _full_passing_evidence()
    gate_result = evaluate_validation_gate(evidence)
    artifact = build_validation_artifact(strategy_id="TEST-STRAT", strategy_version="1.0", strategy_content_hash="abc", evidence=evidence, gate_result=gate_result, approved_by="human:test")
    store = ValidationArtifactStore(tmp_path / "artifacts.jsonl")
    store.approve(artifact)

    conflicting = build_validation_artifact(strategy_id="TEST-STRAT", strategy_version="1.0", strategy_content_hash="DIFFERENT_HASH", evidence=evidence, gate_result=gate_result, approved_by="human:test")
    with pytest.raises(ValidationArtifactImmutabilityError):
        store.approve(conflicting)
