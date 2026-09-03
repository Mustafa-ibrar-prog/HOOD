"""Phase 28, Part 11/17 — the system-level autonomous-trading state
machine: exactly the 7 required states, no per-trade-approval state,
correct code-vs-human-computable transition rules, autonomous pause/
resume and emergency-stop behavior, and a real audit-log round trip."""

from __future__ import annotations

import json

import pytest

from src.execution.system_state import (
    AuthorizationEventType,
    IllegalSystemStateTransitionError,
    StateRequiresHumanActionError,
    SystemAuthorizationEvent,
    SystemState,
    SystemStateAuditLog,
    can_transition,
    record_code_transition,
    record_human_authorized_transition,
)


def test_exactly_seven_required_states():
    assert {s.value for s in SystemState} == {
        "RESEARCH", "PAPER_TRADING", "PAPER_VALIDATED", "HUMAN_LIVE_AUTHORIZATION",
        "LIVE_AUTONOMOUS_TRADING", "LIVE_PAUSED", "EMERGENCY_STOP",
    }


def test_no_waiting_for_trade_approval_state_exists():
    names = {s.name for s in SystemState}
    assert "WAITING_FOR_TRADE_APPROVAL" not in names
    assert not any("TRADE_APPROVAL" in n for n in names)
    assert not any("PER_TRADE" in n for n in names)


def test_forward_progress_through_paper_validated_is_code_computable():
    t1 = record_code_transition(SystemState.RESEARCH, SystemState.PAPER_TRADING, reason="x")
    t2 = record_code_transition(SystemState.PAPER_TRADING, SystemState.PAPER_VALIDATED, reason="x")
    assert t1.authorized_by == "system:code"
    assert t2.authorized_by == "system:code"


def test_code_cannot_reach_human_live_authorization():
    with pytest.raises(StateRequiresHumanActionError):
        record_code_transition(SystemState.PAPER_VALIDATED, SystemState.HUMAN_LIVE_AUTHORIZATION, reason="x")


def test_code_cannot_cross_from_human_live_authorization_into_live_autonomous_trading():
    with pytest.raises(StateRequiresHumanActionError):
        record_code_transition(SystemState.HUMAN_LIVE_AUTHORIZATION, SystemState.LIVE_AUTONOMOUS_TRADING, reason="x")


def test_human_authorized_transition_requires_a_real_human_identifier():
    with pytest.raises(ValueError):
        record_human_authorized_transition(SystemState.PAPER_VALIDATED, SystemState.HUMAN_LIVE_AUTHORIZATION, authorized_by="system:auto", reason="x")
    with pytest.raises(ValueError):
        record_human_authorized_transition(SystemState.PAPER_VALIDATED, SystemState.HUMAN_LIVE_AUTHORIZATION, authorized_by="", reason="x")


def test_human_can_authorize_the_full_activation_sequence():
    t1 = record_human_authorized_transition(SystemState.PAPER_VALIDATED, SystemState.HUMAN_LIVE_AUTHORIZATION, authorized_by="a_real_person", reason="reviewed")
    t2 = record_human_authorized_transition(SystemState.HUMAN_LIVE_AUTHORIZATION, SystemState.LIVE_AUTONOMOUS_TRADING, authorized_by="a_real_person", reason="go live")
    assert t1.authorized_by == t2.authorized_by == "a_real_person"


def test_live_autonomous_trading_can_pause_and_resume_without_human_action():
    """Part 11: 'the system operates independently' -- a routine pause
    (market closed, stale data) and resume must not require a human
    click each time, or this silently reintroduces a per-cycle approval
    gate."""
    t1 = record_code_transition(SystemState.LIVE_AUTONOMOUS_TRADING, SystemState.LIVE_PAUSED, reason="market closed")
    t2 = record_code_transition(SystemState.LIVE_PAUSED, SystemState.LIVE_AUTONOMOUS_TRADING, reason="market reopened")
    assert t1.authorized_by == "system:code"
    assert t2.authorized_by == "system:code"


def test_emergency_stop_is_reachable_autonomously_from_live_autonomous_trading():
    t = record_code_transition(SystemState.LIVE_AUTONOMOUS_TRADING, SystemState.EMERGENCY_STOP, reason="daily loss limit breached")
    assert t.authorized_by == "system:code"


def test_emergency_stop_is_reachable_autonomously_from_paper_states_too():
    assert can_transition(SystemState.RESEARCH, SystemState.EMERGENCY_STOP)
    assert can_transition(SystemState.PAPER_TRADING, SystemState.EMERGENCY_STOP)
    assert can_transition(SystemState.LIVE_PAUSED, SystemState.EMERGENCY_STOP)


def test_emergency_stop_cannot_be_cleared_by_code():
    with pytest.raises((IllegalSystemStateTransitionError, StateRequiresHumanActionError)):
        record_code_transition(SystemState.EMERGENCY_STOP, SystemState.LIVE_AUTONOMOUS_TRADING, reason="auto-resume")


def test_emergency_stop_can_only_be_cleared_via_human_live_authorization():
    assert can_transition(SystemState.EMERGENCY_STOP, SystemState.HUMAN_LIVE_AUTHORIZATION)
    t = record_human_authorized_transition(SystemState.EMERGENCY_STOP, SystemState.HUMAN_LIVE_AUTHORIZATION, authorized_by="a_real_person", reason="reviewed the stop reason, cleared")
    assert t.authorized_by == "a_real_person"


def test_no_transition_skips_a_stage():
    assert not can_transition(SystemState.RESEARCH, SystemState.PAPER_VALIDATED)
    assert not can_transition(SystemState.RESEARCH, SystemState.LIVE_AUTONOMOUS_TRADING)


def test_illegal_transition_raises():
    with pytest.raises(IllegalSystemStateTransitionError):
        record_code_transition(SystemState.RESEARCH, SystemState.LIVE_AUTONOMOUS_TRADING, reason="x")


def test_authorization_event_requires_real_human_identifier():
    from datetime import datetime, timezone
    with pytest.raises(ValueError):
        SystemAuthorizationEvent(AuthorizationEventType.CHANGE_RISK_PARAMETERS, "system:auto", datetime.now(timezone.utc), "x")


def test_audit_log_round_trips_transitions_and_events(tmp_path):
    from datetime import datetime, timezone
    path = tmp_path / "system_state_audit.jsonl"
    log = SystemStateAuditLog(path)
    t1 = record_code_transition(SystemState.RESEARCH, SystemState.PAPER_TRADING, reason="x")
    log.append_transition(t1)
    ev = SystemAuthorizationEvent(AuthorizationEventType.CHANGE_RISK_PARAMETERS, "a_real_person", datetime.now(timezone.utc), "raised max position size")
    log.append_event(ev)

    assert log.current_state() == SystemState.PAPER_TRADING
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["to_state"] == "PAPER_TRADING"
    assert json.loads(lines[1])["event_type"] == "CHANGE_RISK_PARAMETERS"


def test_authorization_event_types_cover_part_11s_preamble_list():
    names = {e.value for e in AuthorizationEventType}
    assert "CHANGE_RISK_PARAMETERS" in names
    assert "CHANGE_STRATEGY_VERSION" in names
    assert "CHANGE_BROKER" in names
    assert "CHANGE_HISTORICAL_DATA_PROVIDER" in names
    assert "DISABLE_SYSTEM" in names
