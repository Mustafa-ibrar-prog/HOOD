"""Phase 38, Part 14 — integration with Phase 36's registry.

`promote_if_validated` is the ONLY function in this phase that can call
`StrategyRegistry.mark_validated` — and it refuses to do so unless
`GateResult.passed` is `True`. There is no other code path anywhere in
this phase that sets a strategy's status to `VALIDATED`/`LIVE_AUTHORIZED`
(verified by `tests/test_phase38_safety.py`, the same AST-scan
convention established in Phase 36's own safety test).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.options.phase38_validation_gate import GateEvidence, GateResult
from src.production.registry import StrategyRegistry, StrategyStatus
from src.production.validation_artifact import ValidationArtifact, ValidationArtifactStore

if TYPE_CHECKING:
    pass


class GateNotPassedError(RuntimeError):
    """Raised by promote_if_validated when the gate has not passed --
    this is the ONLY way this function can be prevented from promoting,
    and it is unconditional: there is no override parameter."""


def build_validation_artifact(
    *, strategy_id: str, strategy_version: str, strategy_content_hash: str, evidence: GateEvidence,
    gate_result: GateResult, approved_by: str, validation_date: datetime | None = None,
) -> ValidationArtifact:
    """Only ever called after `gate_result.passed` is confirmed True by
    the caller (`promote_if_validated`) -- this function itself does not
    re-check the gate, so it must never be called directly to bypass it."""
    return ValidationArtifact(
        strategy_id=strategy_id, strategy_version=strategy_version, strategy_content_hash=strategy_content_hash,
        research_dataset_version="phase38_live_observations_v1",
        feature_definitions="src.options.phase38_causal_validation_dataset.CausalFeatureRow (Phase 37 live observations, joined underlying+option)",
        target_definitions="src.options.phase38_targets.ForwardOutcome (executable bid/ask return, MFE/MAE, multi-horizon)",
        backtest_configuration={"chronological_split": evidence.chronological_split.reason},
        out_of_sample_results={"validation_edge": evidence.validation_edge.detail, "holdout_edge": evidence.holdout_edge.detail},
        cost_assumptions={"cost_stress": [r.__dict__ for r in evidence.cost_stress_results], "spread_stress": [r.__dict__ for r in evidence.spread_stress_results]},
        robustness_results={"leave_one_period_out": {k: v.__dict__ for k, v in evidence.leave_one_period_out.items()}, "leave_one_symbol_out": {k: v.__dict__ for k, v in evidence.leave_one_symbol_out.items()}},
        statistical_results={"economic_report": evidence.economic_report.__dict__},
        multiple_testing_status=f"{len(evidence.test_registry.all())} tests registered via Phase 33 TestRegistry" if evidence.test_registry else "none",
        affordability={"classification": evidence.affordability.classification, "max_simultaneous_positions": evidence.affordability.max_simultaneous_positions_at_equity},
        execution_realism={"executable_return_uses_bid_ask_only": True},
        known_limitations="See docs/phase38_options_strategy_validation.md",
        validation_date=validation_date or datetime.now(timezone.utc),
        validation_decision="VALIDATED_CANDIDATE",
        approved_by=approved_by,
    )


def promote_if_validated(
    *, registry: StrategyRegistry, artifact_store: ValidationArtifactStore, strategy_id: str, strategy_version: str,
    strategy_content_hash: str, evidence: GateEvidence, gate_result: GateResult, approved_by: str,
) -> StrategyStatus:
    """Returns the resulting status. Raises GateNotPassedError (never
    silently promotes) if `gate_result.passed` is False -- this is the
    ONLY function in this phase permitted to call
    `StrategyRegistry.mark_validated`."""
    if not gate_result.passed:
        raise GateNotPassedError(
            f"Validation gate did not pass -- unmet conditions: {gate_result.unmet_condition_names}. "
            "Refusing to promote. status remains NOT_READY."
        )
    artifact = build_validation_artifact(
        strategy_id=strategy_id, strategy_version=strategy_version, strategy_content_hash=strategy_content_hash,
        evidence=evidence, gate_result=gate_result, approved_by=approved_by,
    )
    artifact_store.approve(artifact)
    updated = registry.mark_validated(strategy_id, strategy_version, target_status=StrategyStatus.VALIDATED)
    return updated.status
