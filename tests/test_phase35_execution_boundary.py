"""Phase 35, Parts N-P/R — the execution-boundary hardening.

These tests target `LiveExecutionGateway._place_pending()` directly (the
sole call site of `place_option_order` in this entire codebase, per its
own module docstring) to prove the three new guards it enforces (Part N's
OPTIONS_ONLY, Part O's system-authorization check, Part P's emergency
stop) cannot be bypassed by ANY caller — not a strategy, not the risk
engine, not `live_auto_execute=True` — because none of those layers are
ever in a position to skip `_place_pending` itself; every path
(`submit_order`'s auto-execute branch and `confirm_and_place`) funnels
through it, and it is exercised here with nothing upstream (no strategy,
no RiskManager) standing between the caller and the gateway, which is
precisely the point: even a hypothetical caller that skipped every
upstream check still cannot get a real order placed without these three
gates passing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.execution.emergency_stop import EmergencyStopStore
from src.execution.gateway import LiveExecutionGateway, LiveTradingDisabledError
from src.execution.live_positions import LiveBotPositionsStore
from src.execution.orders import OrderLeg, OrderRequest
from src.execution.pending import PendingOrderStore
from src.execution.system_state import (
    SystemState,
    SystemStateAuditLog,
    record_code_transition,
    record_human_authorized_transition,
)
from src.logging.decision_logger import DecisionLogger


@pytest.fixture
def decision_logger(tmp_path) -> DecisionLogger:
    return DecisionLogger(path=tmp_path / "decisions.jsonl", also_console=False)


@pytest.fixture
def buy_order() -> OrderRequest:
    return OrderRequest(
        account_number="987155785",
        legs=(OrderLeg(option_id="opt-1", side="buy", position_effect="open"),),
        quantity="1", type="limit", price="0.95", ref_id="ref-1", reason="BUY: breakout",
    )


class FakePlacer:
    def __init__(self, response: dict | None = None):
        self.calls: list[dict] = []
        self._response = response or {"id": "order-abc", "state": "confirmed"}

    def place_option_order(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def _fully_authorized_audit_log(path: Path) -> SystemStateAuditLog:
    log = SystemStateAuditLog(path)
    t1 = record_code_transition(SystemState.RESEARCH, SystemState.VALIDATED_STRATEGY, reason="x")
    log.append_transition(t1)
    t2 = record_human_authorized_transition(
        SystemState.VALIDATED_STRATEGY, SystemState.HUMAN_LIVE_AUTHORIZATION, authorized_by="user:test", reason="x"
    )
    log.append_transition(t2)
    t3 = record_human_authorized_transition(
        SystemState.HUMAN_LIVE_AUTHORIZATION, SystemState.LIVE_AUTONOMOUS_TRADING, authorized_by="user:test", reason="x"
    )
    log.append_transition(t3)
    return log


def _cleared_stop_store(path: Path) -> EmergencyStopStore:
    store = EmergencyStopStore(path)
    store.clear(authorized_by="user:test", reason="test")
    return store


def _gateway(settings, decision_logger, tmp_path, *, stop_store=None, audit_log=None, live_order_placer=None) -> LiveExecutionGateway:
    pending_store = PendingOrderStore(Path(settings.pending_orders_file))
    bot_positions = LiveBotPositionsStore(Path(settings.live_bot_positions_file))
    return LiveExecutionGateway(
        settings, decision_logger, pending_store, bot_positions, live_order_placer,
        emergency_stop_store=stop_store, system_state_audit_log=audit_log,
    )


# --- Part P: emergency stop cannot be bypassed ---------------------------------------------


def test_emergency_stop_blocks_confirm_and_place_even_with_full_authorization(
    live_confirmed_settings, decision_logger, buy_order, tmp_path
):
    """Fully authorized system state (LIVE_AUTONOMOUS_TRADING) is NOT
    enough on its own -- an active emergency stop still blocks the real
    broker call. This is the 'strategy cannot bypass stop' /
    'risk cannot bypass stop' property: neither layer is even
    consulted here, and the order is still refused."""
    stop_store = EmergencyStopStore(tmp_path / "stop.json")  # never cleared -- defaults to STOPPED
    audit_log = _fully_authorized_audit_log(tmp_path / "audit.jsonl")
    gateway = _gateway(live_confirmed_settings, decision_logger, tmp_path, stop_store=stop_store, audit_log=audit_log)

    pending_id = gateway.submit_order(buy_order).extra["pending_order_id"]
    placer = FakePlacer()
    with pytest.raises(LiveTradingDisabledError, match="[Ee]mergency stop"):
        gateway.confirm_and_place(pending_id, placer, approved_by="user:test")
    assert placer.calls == []  # place_option_order never reached


def test_live_auto_execute_submit_order_raises_when_stop_is_active(live_confirmed_settings, decision_logger, buy_order, tmp_path):
    """live_auto_execute=True's whole point is to skip the human-approval
    pause -- it must NOT also skip the emergency-stop check. Constructed
    exactly like the real auto-execute path (a LiveOrderPlacer injected at
    construction, settings.live_auto_execute=True) but with the stop left
    tripped."""
    from dataclasses import replace

    auto_settings = replace(live_confirmed_settings, live_auto_execute=True)
    stop_store = EmergencyStopStore(tmp_path / "stop.json")  # left STOPPED
    audit_log = _fully_authorized_audit_log(tmp_path / "audit.jsonl")
    placer = FakePlacer()
    gateway = _gateway(auto_settings, decision_logger, tmp_path, stop_store=stop_store, audit_log=audit_log, live_order_placer=placer)

    with pytest.raises(LiveTradingDisabledError, match="[Ee]mergency stop"):
        gateway.submit_order(buy_order)
    assert placer.calls == []


def test_emergency_stop_restart_preserves_stopped_state(tmp_path):
    """Part P: 'survives process restart.' A fresh EmergencyStopStore
    instance pointed at the same file (simulating a restart) must see the
    same active=True default -- nothing about restarting silently clears
    it."""
    path = tmp_path / "stop.json"
    store1 = EmergencyStopStore(path)
    assert store1.is_stopped()  # brand new -- defaults to STOPPED
    store2 = EmergencyStopStore(path)  # fresh instance, as if the process restarted
    assert store2.is_stopped()


def test_emergency_stop_restart_preserves_cleared_state(tmp_path):
    path = tmp_path / "stop.json"
    store1 = EmergencyStopStore(path)
    store1.clear(authorized_by="user:test", reason="reviewed")
    store2 = EmergencyStopStore(path)  # fresh instance, as if the process restarted
    assert not store2.is_stopped()


def test_emergency_stop_activate_requires_no_authorization(tmp_path):
    """A kill switch must be trivially easy to trip -- by anyone/anything,
    including automated code reacting to a risk breach."""
    store = EmergencyStopStore(tmp_path / "stop.json")
    store.clear(authorized_by="user:test", reason="cleared for trading")
    assert not store.is_stopped()
    store.activate(reason="daily loss limit breached", set_by="system:risk_auto_stop")
    assert store.is_stopped()


def test_emergency_stop_clear_rejects_system_identity(tmp_path):
    store = EmergencyStopStore(tmp_path / "stop.json")
    with pytest.raises(ValueError):
        store.clear(authorized_by="system:auto", reason="x")
    with pytest.raises(ValueError):
        store.clear(authorized_by="", reason="x")


# --- Part O: unauthorized system state blocks execution ------------------------------------


@pytest.mark.parametrize("blocking_state", [SystemState.RESEARCH, SystemState.VALIDATED_STRATEGY, SystemState.HUMAN_LIVE_AUTHORIZATION, SystemState.LIVE_PAUSED, SystemState.EMERGENCY_STOP])
def test_unauthorized_system_state_blocks_execution_even_with_stop_cleared(
    live_confirmed_settings, decision_logger, buy_order, tmp_path, blocking_state
):
    """Every state other than LIVE_AUTONOMOUS_TRADING must block a real
    placement -- even with the emergency stop cleared and a placer ready
    to accept the call."""
    stop_store = _cleared_stop_store(tmp_path / "stop.json")
    audit_path = tmp_path / "audit.jsonl"
    if blocking_state == SystemState.RESEARCH:
        audit_log = SystemStateAuditLog(audit_path)  # no transitions at all -- current_state() is None, treated the same as RESEARCH for this test's purpose
    else:
        # Force the audit log to whatever state we're testing by writing a
        # transition record directly (some of these states aren't legally
        # reachable via the normal forward-progress helpers in one hop from
        # RESEARCH, and that's fine -- this test only cares what
        # is_live_trading_authorized does for a given CURRENT state).
        import json
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps({
            "from_state": "RESEARCH", "to_state": blocking_state.value,
            "timestamp": "2026-01-01T00:00:00+00:00", "authorized_by": "system:code", "reason": "test",
        }) + "\n")
        audit_log = SystemStateAuditLog(audit_path)  # loads the forced state back from disk

    gateway = _gateway(live_confirmed_settings, decision_logger, tmp_path, stop_store=stop_store, audit_log=audit_log)
    pending_id = gateway.submit_order(buy_order).extra["pending_order_id"]
    placer = FakePlacer()
    with pytest.raises(LiveTradingDisabledError, match="not authorized"):
        gateway.confirm_and_place(pending_id, placer, approved_by="user:test")
    assert placer.calls == []


def test_no_record_at_all_blocks_execution(live_confirmed_settings, decision_logger, buy_order, tmp_path):
    """A brand-new deployment (no audit log file yet) must be blocked,
    never treated as permissively-authorized."""
    stop_store = _cleared_stop_store(tmp_path / "stop.json")
    audit_log = SystemStateAuditLog(tmp_path / "audit.jsonl")  # nothing appended -- current_state() is None
    gateway = _gateway(live_confirmed_settings, decision_logger, tmp_path, stop_store=stop_store, audit_log=audit_log)
    pending_id = gateway.submit_order(buy_order).extra["pending_order_id"]
    placer = FakePlacer()
    with pytest.raises(LiveTradingDisabledError, match="not authorized"):
        gateway.confirm_and_place(pending_id, placer, approved_by="user:test")
    assert placer.calls == []


def test_missing_stores_altogether_block_execution(live_confirmed_settings, decision_logger, buy_order, tmp_path):
    """Omitting the stores entirely (the pre-Phase-35 constructor shape)
    must not silently skip these checks -- None is treated as blocked,
    not permissive."""
    gateway = _gateway(live_confirmed_settings, decision_logger, tmp_path)  # no stop_store/audit_log passed
    pending_id = gateway.submit_order(buy_order).extra["pending_order_id"]
    placer = FakePlacer()
    with pytest.raises(LiveTradingDisabledError):
        gateway.confirm_and_place(pending_id, placer, approved_by="user:test")
    assert placer.calls == []


def test_fully_authorized_and_cleared_stop_allows_placement(live_confirmed_settings, decision_logger, buy_order, tmp_path):
    """The positive case: both gates satisfied -- placement proceeds
    exactly as before Phase 35's hardening."""
    stop_store = _cleared_stop_store(tmp_path / "stop.json")
    audit_log = _fully_authorized_audit_log(tmp_path / "audit.jsonl")
    gateway = _gateway(live_confirmed_settings, decision_logger, tmp_path, stop_store=stop_store, audit_log=audit_log)
    pending_id = gateway.submit_order(buy_order).extra["pending_order_id"]
    placer = FakePlacer(response={"id": "order-ok", "state": "confirmed"})
    result = gateway.confirm_and_place(pending_id, placer, approved_by="user:test")
    assert result.status == "placed"
    assert len(placer.calls) == 1


# --- Part N: OPTIONS_ONLY is actually enforced at the gateway -------------------------------


def test_options_only_is_enforced_at_the_gateway_not_merely_by_construction(
    live_confirmed_settings, decision_logger, tmp_path
):
    """assert_options_only is now actually CALLED inside _place_pending --
    verified here by constructing a syntactically-valid OrderRequest whose
    leg carries an empty option_id (OrderLeg itself doesn't forbid an
    empty string, only requires the field to exist) and confirming the
    gateway itself refuses it, independent of whatever upstream code
    normally prevents this from being constructed."""
    stop_store = _cleared_stop_store(tmp_path / "stop.json")
    audit_log = _fully_authorized_audit_log(tmp_path / "audit.jsonl")
    gateway = _gateway(live_confirmed_settings, decision_logger, tmp_path, stop_store=stop_store, audit_log=audit_log)

    bad_order = OrderRequest(
        account_number="987155785",
        legs=(OrderLeg(option_id="", side="buy", position_effect="open"),),
        quantity="1", type="limit", price="0.95", ref_id="ref-bad", reason="test",
    )
    pending_id = gateway.submit_order(bad_order).extra["pending_order_id"]
    placer = FakePlacer()
    with pytest.raises(Exception):  # NonOptionsOrderRejected
        gateway.confirm_and_place(pending_id, placer, approved_by="user:test")
    assert placer.calls == []
