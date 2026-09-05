"""Phase 36, Parts 15-17 — verification (not modification) that:
  - the pipeline has no per-trade approval state (autonomous execution compatibility)
  - human authorization remains system-level only (reused from Phase 35, unchanged)
  - the emergency stop remains unweakened (reused from Phase 35, unchanged)
"""

from __future__ import annotations

import dataclasses

from src.execution.emergency_stop import EmergencyStopStore
from src.execution.system_state import SystemState
from src.production.pipeline import PipelineResult


# --- Part 15: no per-trade approval state -------------------------------------------------------


def test_pipeline_result_has_no_per_trade_approval_field():
    field_names = {f.name for f in dataclasses.fields(PipelineResult)}
    for forbidden in ("approved", "approved_by", "pending_approval", "awaiting_approval", "human_approval"):
        assert forbidden not in field_names


def test_system_state_still_exactly_six_states_with_no_per_trade_state():
    """Phase 36 does not touch system_state.py at all -- reconfirms Phase
    35's invariant still holds unchanged."""
    assert len(SystemState) == 6
    names = {s.name for s in SystemState}
    assert "WAITING_FOR_TRADE_APPROVAL" not in names
    assert not any("PER_TRADE" in n for n in names)


# --- Part 16: human authorization is system-level only ------------------------------------------


def test_authorization_gate_is_a_system_level_state_not_a_per_opportunity_field():
    """The only authorization concept this pipeline reads is
    is_live_trading_authorized(system_state_audit_log) -- a single,
    system-wide boolean, never per-Opportunity/per-decision state."""
    from src.production.opportunity import Opportunity

    field_names = {f.name for f in dataclasses.fields(Opportunity)}
    assert "authorized" not in field_names
    assert "approved_by" not in field_names


def test_record_human_authorized_transition_still_rejects_system_identity():
    from src.execution.system_state import record_human_authorized_transition
    import pytest

    with pytest.raises(ValueError):
        record_human_authorized_transition(
            SystemState.VALIDATED_STRATEGY, SystemState.HUMAN_LIVE_AUTHORIZATION,
            authorized_by="system:auto", reason="x",
        )


# --- Part 17: emergency stop unweakened ----------------------------------------------------------


def test_emergency_stop_still_defaults_to_stopped(tmp_path):
    store = EmergencyStopStore(tmp_path / "does_not_exist.json")
    assert store.is_stopped() is True


def test_emergency_stop_clear_still_requires_a_real_human_identity(tmp_path):
    import pytest

    store = EmergencyStopStore(tmp_path / "stop.json")
    with pytest.raises(ValueError):
        store.clear(authorized_by="system:auto", reason="x")


def test_pipeline_never_calls_emergency_stop_activate_or_clear():
    source = (__import__("pathlib").Path(__file__).resolve().parent.parent / "src/production/pipeline.py").read_text()
    assert ".activate(" not in source
    assert ".clear(" not in source
