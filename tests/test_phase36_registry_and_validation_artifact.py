"""Phase 36, Part 4-5 — StrategyRegistry + ValidationArtifact."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.production.registry import (
    StrategyMetadata,
    StrategyNotEligibleError,
    StrategyRegistry,
    StrategyStatus,
    build_default_registry,
)
from src.production.validation_artifact import (
    IncompleteValidationEvidenceError,
    ValidationArtifact,
    ValidationArtifactImmutabilityError,
    ValidationArtifactStore,
)


def _now():
    return datetime(2026, 9, 5, tzinfo=timezone.utc)


def _metadata(strategy_id="TEST-STRAT", version="1.0", status=StrategyStatus.RESEARCH) -> StrategyMetadata:
    return StrategyMetadata(
        strategy_id=strategy_id, version=version, status=status, created_at=_now(),
        validation_status="unknown", historical_evidence_status="unknown",
        live_data_compatibility_status="unknown", allowed_option_structures=("long_call",),
        parameter_specification="none", risk_profile="test", author_or_research_provenance="test",
    )


def _artifact(strategy_id="TEST-STRAT", version="1.0", decision="VALIDATED_CANDIDATE") -> ValidationArtifact:
    return ValidationArtifact(
        strategy_id=strategy_id, strategy_version=version, strategy_content_hash="abc123",
        research_dataset_version="v1", feature_definitions="rsi14", target_definitions="5d fwd return",
        backtest_configuration={"engine": "BacktestEngine"}, out_of_sample_results={"n_trades": 100},
        cost_assumptions={"slippage": 0.01}, robustness_results={"loo": "pass"},
        statistical_results={"bootstrap_ci": [0.01, 0.05]}, multiple_testing_status="corrected",
        affordability={"pct_affordable": 0.9}, execution_realism={"cost_stress": "5x pass"},
        known_limitations="test fixture", validation_date=_now(), validation_decision=decision,
        approved_by="human:test",
    )


# --- StrategyRegistry ------------------------------------------------------------------------


def test_registry_rejects_non_validated_from_production_eligible():
    registry = StrategyRegistry()
    registry.register(_metadata(status=StrategyStatus.NOT_READY))
    assert registry.production_eligible_strategies() == ()


def test_registry_production_eligible_includes_validated_and_live_authorized():
    store = ValidationArtifactStore.__new__(ValidationArtifactStore)  # unused here; direct registration path
    registry = StrategyRegistry()
    registry.register(_metadata(status=StrategyStatus.VALIDATED))
    registry.register(_metadata(strategy_id="TEST-STRAT-2", status=StrategyStatus.LIVE_AUTHORIZED))
    registry.register(_metadata(strategy_id="TEST-STRAT-3", status=StrategyStatus.REJECTED))
    assert {m.strategy_id for m in registry.production_eligible_strategies()} == {"TEST-STRAT", "TEST-STRAT-2"}


def test_mark_validated_requires_a_real_artifact(tmp_path):
    store = ValidationArtifactStore(tmp_path / "artifacts.jsonl")
    registry = StrategyRegistry(store)
    registry.register(_metadata())
    with pytest.raises(StrategyNotEligibleError):
        registry.mark_validated("TEST-STRAT", "1.0")


def test_mark_validated_succeeds_with_a_real_artifact(tmp_path):
    store = ValidationArtifactStore(tmp_path / "artifacts.jsonl")
    store.approve(_artifact())
    registry = StrategyRegistry(store)
    registry.register(_metadata())
    updated = registry.mark_validated("TEST-STRAT", "1.0")
    assert updated.status == StrategyStatus.VALIDATED
    assert registry.production_eligible_strategies() == (updated,)


def test_mark_validated_fails_without_a_configured_artifact_store():
    registry = StrategyRegistry(artifact_store=None)
    registry.register(_metadata())
    with pytest.raises(StrategyNotEligibleError):
        registry.mark_validated("TEST-STRAT", "1.0")


def test_default_registry_has_momentum_breakout_at_not_ready():
    registry = build_default_registry()
    entry = registry.get("MOMENTUM_BREAKOUT_EXISTING_V1", "1.0")
    assert entry is not None
    assert entry.status == StrategyStatus.NOT_READY
    assert registry.production_eligible_strategies() == ()


# --- ValidationArtifact -----------------------------------------------------------------------


def test_validation_artifact_rejects_placeholder_fields():
    with pytest.raises(IncompleteValidationEvidenceError):
        _artifact_missing = ValidationArtifact(
            strategy_id="X", strategy_version="1.0", strategy_content_hash="", research_dataset_version="v1",
            feature_definitions="rsi", target_definitions="ret", backtest_configuration={"a": 1},
            out_of_sample_results={"a": 1}, cost_assumptions={"a": 1}, robustness_results={"a": 1},
            statistical_results={"a": 1}, multiple_testing_status="none", affordability={"a": 1},
            execution_realism={"a": 1}, known_limitations="x", validation_date=_now(),
            validation_decision="VALIDATED_CANDIDATE", approved_by="human:test",
        )


def test_validation_artifact_rejects_empty_evidence_dict():
    with pytest.raises(IncompleteValidationEvidenceError):
        ValidationArtifact(
            strategy_id="X", strategy_version="1.0", strategy_content_hash="abc", research_dataset_version="v1",
            feature_definitions="rsi", target_definitions="ret", backtest_configuration={},
            out_of_sample_results={"a": 1}, cost_assumptions={"a": 1}, robustness_results={"a": 1},
            statistical_results={"a": 1}, multiple_testing_status="none", affordability={"a": 1},
            execution_realism={"a": 1}, known_limitations="x", validation_date=_now(),
            validation_decision="VALIDATED_CANDIDATE", approved_by="human:test",
        )


def test_validation_artifact_store_immutable_on_conflicting_reapproval(tmp_path):
    store = ValidationArtifactStore(tmp_path / "artifacts.jsonl")
    store.approve(_artifact())
    conflicting = _artifact(decision="REJECTED")
    with pytest.raises(ValidationArtifactImmutabilityError):
        store.approve(conflicting)


def test_validation_artifact_store_idempotent_on_identical_reapproval(tmp_path):
    store = ValidationArtifactStore(tmp_path / "artifacts.jsonl")
    a1 = store.approve(_artifact())
    a2 = store.approve(_artifact())
    assert a1.content_hash() == a2.content_hash()


def test_validation_artifact_round_trips_through_store(tmp_path):
    store = ValidationArtifactStore(tmp_path / "artifacts.jsonl")
    store.approve(_artifact())
    loaded = store.get("TEST-STRAT", "1.0")
    assert loaded is not None
    assert loaded.validation_decision == "VALIDATED_CANDIDATE"
