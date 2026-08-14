"""Tests for the live-execution architecture: pending orders, the
provenance store, preflight checks, and every path through
LiveExecutionGateway — including the property that _place_pending() (via
confirm_and_place or submit_order's auto-execute path) is the ONLY way
place_option_order ever gets called."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.execution.gateway import (
    LiveExecutionGateway,
    PendingOrderNotActionableError,
    get_execution_gateway,
)
from src.execution.live_positions import LiveBotPositionsStore
from src.execution.orders import OrderLeg, OrderRequest
from src.execution.pending import PendingLiveOrder, PendingOrderStore, PendingOrderStoreError
from src.execution.preflight import verify_account_preflight
from src.live_bridge import StaticLiveOrderPlacer
from src.logging.decision_logger import DecisionLogger


@pytest.fixture
def decision_logger(tmp_path) -> DecisionLogger:
    return DecisionLogger(path=tmp_path / "decisions.jsonl", also_console=False)


@pytest.fixture
def buy_order() -> OrderRequest:
    return OrderRequest(
        account_number="987155785",
        legs=(OrderLeg(option_id="opt-1", side="buy", position_effect="open"),),
        quantity="1",
        type="limit",
        price="0.95",
        ref_id="ref-1",
        reason="BUY: breakout",
    )


@pytest.fixture
def sell_order() -> OrderRequest:
    return OrderRequest(
        account_number="987155785",
        legs=(OrderLeg(option_id="opt-1", side="sell", position_effect="close"),),
        quantity="1",
        type="limit",
        price="1.05",
        ref_id="ref-2",
        reason="TARGET_EXIT: target reached",
    )


class FakePlacer:
    """Records every place_option_order call it receives so tests can
    assert it was called exactly once, with the expected params — this IS
    the mock that stands in for a real (never invoked in tests)
    place_option_order tool call."""

    def __init__(self, response: dict | None = None, raise_error: Exception | None = None):
        self.calls: list[dict] = []
        self._response = response or {"id": "order-abc", "state": "confirmed"}
        self._raise_error = raise_error

    def get_accounts(self):
        raise NotImplementedError

    def get_portfolio(self, account_number):
        raise NotImplementedError

    def review_option_order(self, **kwargs):
        raise NotImplementedError

    def place_option_order(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise_error:
            raise self._raise_error
        return self._response

    def cancel_option_order(self, **kwargs):
        raise NotImplementedError


# --- PendingOrderStore --------------------------------------------------------------------


def test_pending_order_store_round_trips(tmp_path, buy_order):
    store = PendingOrderStore(tmp_path / "pending.json")
    pending = PendingLiveOrder.new(order=buy_order, expiry_minutes=15)
    store.add(pending)

    loaded = store.get(pending.id)
    assert loaded is not None
    assert loaded.status == "awaiting_approval"
    assert loaded.order.legs[0].option_id == "opt-1"


def test_pending_order_store_update_requires_existing_record(tmp_path, buy_order):
    store = PendingOrderStore(tmp_path / "pending.json")
    pending = PendingLiveOrder.new(order=buy_order, expiry_minutes=15)
    with pytest.raises(PendingOrderStoreError):
        store.update(pending)  # never added


def test_pending_order_store_expire_stale(tmp_path, buy_order):
    store = PendingOrderStore(tmp_path / "pending.json")
    now = datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)
    pending = PendingLiveOrder.new(order=buy_order, expiry_minutes=15, now=now)
    store.add(pending)

    later = now + timedelta(minutes=16)
    expired = store.expire_stale(later)
    assert len(expired) == 1
    assert expired[0].status == "expired"
    assert store.get(pending.id).status == "expired"


def test_pending_order_store_corrupted_file_fails_closed(tmp_path):
    path = tmp_path / "pending.json"
    path.write_text("{not valid json")
    store = PendingOrderStore(path)
    with pytest.raises(PendingOrderStoreError):
        store.load()


# --- LiveBotPositionsStore -----------------------------------------------------------------


def test_bot_positions_store_add_remove_contains(tmp_path):
    store = LiveBotPositionsStore(tmp_path / "bot_positions.json")
    assert not store.contains("opt-1")
    store.add("opt-1")
    assert store.contains("opt-1")
    store.remove("opt-1")
    assert not store.contains("opt-1")


# --- preflight ----------------------------------------------------------------------------


def test_preflight_passes_for_agentic_allowed_option_level_2_account():
    accounts_response = {
        "results": [
            {"account_number": "987155785", "agentic_allowed": True, "option_level": "option_level_2", "state": "active"}
        ]
    }
    portfolio_response = {"buying_power": "1000.00"}
    result = verify_account_preflight(
        accounts_response=accounts_response,
        portfolio_response=portfolio_response,
        account_number="987155785",
        max_position_size_usd=250.0,
    )
    assert result.ok
    assert result.buying_power_usd == 1000.0
    result.require_ok()  # must not raise


def test_preflight_fails_when_agentic_not_allowed():
    accounts_response = {"results": [{"account_number": "987155785", "agentic_allowed": False, "option_level": "option_level_2"}]}
    result = verify_account_preflight(
        accounts_response=accounts_response,
        portfolio_response={"buying_power": "1000"},
        account_number="987155785",
        max_position_size_usd=250.0,
    )
    assert not result.ok
    assert any("agentic_allowed" in f for f in result.failures)
    with pytest.raises(Exception):
        result.require_ok()


def test_preflight_fails_when_option_level_insufficient():
    accounts_response = {"results": [{"account_number": "987155785", "agentic_allowed": True, "option_level": "option_level_0"}]}
    result = verify_account_preflight(
        accounts_response=accounts_response,
        portfolio_response={"buying_power": "1000"},
        account_number="987155785",
        max_position_size_usd=250.0,
    )
    assert not result.ok
    assert any("option_level" in f for f in result.failures)


def test_preflight_fails_when_account_not_found():
    result = verify_account_preflight(
        accounts_response={"results": []},
        portfolio_response=None,
        account_number="000000",
        max_position_size_usd=250.0,
    )
    assert not result.ok
    assert "not found" in result.failures[0]


def test_preflight_fails_when_buying_power_below_max_position_size():
    accounts_response = {"results": [{"account_number": "987155785", "agentic_allowed": True, "option_level": "option_level_2"}]}
    result = verify_account_preflight(
        accounts_response=accounts_response,
        portfolio_response={"buying_power": "50.00"},
        account_number="987155785",
        max_position_size_usd=250.0,
    )
    assert not result.ok
    assert any("buying_power" in f for f in result.failures)


# --- LiveExecutionGateway: confirm_and_place is the sole path to place_option_order --------


def test_confirm_and_place_calls_placer_exactly_once_and_records_live_fill(
    live_confirmed_settings, decision_logger, buy_order
):
    pending_store = PendingOrderStore(Path(live_confirmed_settings.pending_orders_file))
    bot_positions = LiveBotPositionsStore(Path(live_confirmed_settings.live_bot_positions_file))
    gateway = LiveExecutionGateway(live_confirmed_settings, decision_logger, pending_store, bot_positions)

    submitted = gateway.submit_order(buy_order)
    assert submitted.status == "pending_approval"
    pending_id = submitted.extra["pending_order_id"]

    placer = FakePlacer(response={"id": "order-xyz", "state": "confirmed"})
    result = gateway.confirm_and_place(pending_id, placer, approved_by="user:test")

    assert result.status == "placed"
    assert result.live_fill is not None
    assert result.live_fill.order_id == "order-xyz"
    assert len(placer.calls) == 1
    assert placer.calls[0]["account_number"] == "987155785"
    assert placer.calls[0]["ref_id"] == "ref-1"

    # provenance: a BUY-to-open leg gets tracked as the bot's own
    assert bot_positions.contains("opt-1")

    stored = pending_store.get(pending_id)
    assert stored.status == "placed"
    assert stored.decided_by == "user:test"


def test_confirm_and_place_close_leg_removes_bot_position_provenance(
    live_confirmed_settings, decision_logger, sell_order
):
    pending_store = PendingOrderStore(Path(live_confirmed_settings.pending_orders_file))
    bot_positions = LiveBotPositionsStore(Path(live_confirmed_settings.live_bot_positions_file))
    bot_positions.add("opt-1")  # simulate a prior confirmed entry
    gateway = LiveExecutionGateway(live_confirmed_settings, decision_logger, pending_store, bot_positions)

    submitted = gateway.submit_order(sell_order)
    placer = FakePlacer()
    gateway.confirm_and_place(submitted.extra["pending_order_id"], placer, approved_by="user:test")

    assert not bot_positions.contains("opt-1")


def test_confirm_and_place_refuses_unknown_pending_id(live_confirmed_settings, decision_logger):
    pending_store = PendingOrderStore(Path(live_confirmed_settings.pending_orders_file))
    gateway = LiveExecutionGateway(live_confirmed_settings, decision_logger, pending_store)
    with pytest.raises(PendingOrderNotActionableError):
        gateway.confirm_and_place("does-not-exist", FakePlacer(), approved_by="user:test")


def test_confirm_and_place_refuses_already_decided_pending(live_confirmed_settings, decision_logger, buy_order):
    pending_store = PendingOrderStore(Path(live_confirmed_settings.pending_orders_file))
    gateway = LiveExecutionGateway(live_confirmed_settings, decision_logger, pending_store)
    pending_id = gateway.submit_order(buy_order).extra["pending_order_id"]

    gateway.confirm_and_place(pending_id, FakePlacer(), approved_by="user:test")
    # A second confirmation attempt on the same, now-"placed" order must be
    # refused — this is the guarantee against double-placing.
    with pytest.raises(PendingOrderNotActionableError):
        gateway.confirm_and_place(pending_id, FakePlacer(), approved_by="user:test-again")


def test_confirm_and_place_refuses_expired_pending(live_confirmed_settings, decision_logger, buy_order):
    pending_store = PendingOrderStore(Path(live_confirmed_settings.pending_orders_file))
    gateway = LiveExecutionGateway(live_confirmed_settings, decision_logger, pending_store)
    pending_id = gateway.submit_order(buy_order).extra["pending_order_id"]

    later = pending_store.get(pending_id).expires_at + timedelta(minutes=1)
    placer = FakePlacer()
    with pytest.raises(PendingOrderNotActionableError):
        gateway.confirm_and_place(pending_id, placer, approved_by="user:test", now=later)
    assert placer.calls == []  # never reached place_option_order
    assert pending_store.get(pending_id).status == "expired"


def test_confirm_and_place_records_failure_and_reraises(live_confirmed_settings, decision_logger, buy_order):
    pending_store = PendingOrderStore(Path(live_confirmed_settings.pending_orders_file))
    gateway = LiveExecutionGateway(live_confirmed_settings, decision_logger, pending_store)
    pending_id = gateway.submit_order(buy_order).extra["pending_order_id"]

    placer = FakePlacer(raise_error=RuntimeError("insufficient buying power"))
    with pytest.raises(RuntimeError):
        gateway.confirm_and_place(pending_id, placer, approved_by="user:test")

    stored = pending_store.get(pending_id)
    assert stored.status == "failed"
    assert "insufficient buying power" in stored.error


def test_reject_pending_marks_rejected_without_ever_calling_placer(live_confirmed_settings, decision_logger, buy_order):
    pending_store = PendingOrderStore(Path(live_confirmed_settings.pending_orders_file))
    gateway = LiveExecutionGateway(live_confirmed_settings, decision_logger, pending_store)
    pending_id = gateway.submit_order(buy_order).extra["pending_order_id"]

    rejected = gateway.reject_pending(pending_id, reason="spread too wide now", rejected_by="user:test")
    assert rejected.status == "rejected"
    assert pending_store.get(pending_id).status == "rejected"


def test_reject_pending_refuses_already_decided(live_confirmed_settings, decision_logger, buy_order):
    pending_store = PendingOrderStore(Path(live_confirmed_settings.pending_orders_file))
    gateway = LiveExecutionGateway(live_confirmed_settings, decision_logger, pending_store)
    pending_id = gateway.submit_order(buy_order).extra["pending_order_id"]
    gateway.reject_pending(pending_id, reason="no", rejected_by="user:test")
    with pytest.raises(PendingOrderNotActionableError):
        gateway.reject_pending(pending_id, reason="no again", rejected_by="user:test")


# --- LiveExecutionGateway: auto-execute path ------------------------------------------------


def test_submit_order_auto_executes_when_flag_set_and_placer_injected(tmp_path, decision_logger, buy_order):
    from src.config.settings import Settings

    env = {
        "TRADING_MODE": "live",
        "LIVE_TRADING_CONFIRMED": "true",
        "LIVE_AUTO_EXECUTE": "true",
        "LOG_DIR": str(tmp_path / "logs"),
        "DECISION_LOG_FILE": str(tmp_path / "logs" / "decisions.jsonl"),
        "APP_LOG_FILE": str(tmp_path / "logs" / "app.log"),
        "RISK_STATE_FILE": str(tmp_path / "logs" / "risk_state.json"),
        "PAPER_POSITIONS_FILE": str(tmp_path / "logs" / "paper_positions.json"),
        "PENDING_ORDERS_FILE": str(tmp_path / "logs" / "pending_orders.json"),
        "LIVE_BOT_POSITIONS_FILE": str(tmp_path / "logs" / "live_bot_positions.json"),
    }
    settings = Settings.from_env(env=env)
    pending_store = PendingOrderStore(Path(settings.pending_orders_file))
    bot_positions = LiveBotPositionsStore(Path(settings.live_bot_positions_file))
    placer = FakePlacer(response={"id": "order-auto", "state": "confirmed"})

    gateway = LiveExecutionGateway(settings, decision_logger, pending_store, bot_positions, placer)
    result = gateway.submit_order(buy_order)

    assert result.status == "placed"
    assert result.live_fill.order_id == "order-auto"
    assert len(placer.calls) == 1
    assert bot_positions.contains("opt-1")
    # audit trail still exists even though no human approval step ran
    all_pending = pending_store.load()
    assert len(all_pending) == 1
    assert all_pending[0].status == "placed"
    assert all_pending[0].decided_by == "system:auto_execute"


def test_submit_order_stays_pending_when_auto_execute_true_but_no_placer_injected(
    live_confirmed_settings, decision_logger, buy_order
):
    from dataclasses import replace

    auto_settings = replace(live_confirmed_settings, live_auto_execute=True)
    pending_store = PendingOrderStore(Path(auto_settings.pending_orders_file))
    gateway = LiveExecutionGateway(auto_settings, decision_logger, pending_store)  # no live_order_placer
    result = gateway.submit_order(buy_order)
    assert result.status == "pending_approval"


def test_get_execution_gateway_threads_live_order_placer(tmp_path, decision_logger):
    from src.config.settings import Settings

    env = {
        "TRADING_MODE": "live",
        "LIVE_TRADING_CONFIRMED": "true",
        "LIVE_AUTO_EXECUTE": "true",
        "LOG_DIR": str(tmp_path / "logs"),
        "DECISION_LOG_FILE": str(tmp_path / "logs" / "decisions.jsonl"),
        "APP_LOG_FILE": str(tmp_path / "logs" / "app.log"),
        "RISK_STATE_FILE": str(tmp_path / "logs" / "risk_state.json"),
        "PAPER_POSITIONS_FILE": str(tmp_path / "logs" / "paper_positions.json"),
        "PENDING_ORDERS_FILE": str(tmp_path / "logs" / "pending_orders.json"),
        "LIVE_BOT_POSITIONS_FILE": str(tmp_path / "logs" / "live_bot_positions.json"),
    }
    settings = Settings.from_env(env=env)
    pending_store = PendingOrderStore(Path(settings.pending_orders_file))
    placer = FakePlacer()
    gateway = get_execution_gateway(settings, decision_logger, pending_store, live_order_placer=placer)
    assert isinstance(gateway, LiveExecutionGateway)


# --- StaticLiveOrderPlacer (agent-mediated bridge) -------------------------------------------


def test_static_live_order_placer_returns_recorded_place_result():
    placer = StaticLiveOrderPlacer()
    placer.record_place_option_order({"id": "order-real", "state": "confirmed"})
    result = placer.place_option_order(account_number="987155785", legs=[], quantity="1")
    assert result == {"id": "order-real", "state": "confirmed"}


def test_static_live_order_placer_raises_if_nothing_recorded():
    placer = StaticLiveOrderPlacer()
    with pytest.raises(KeyError):
        placer.place_option_order(account_number="987155785", legs=[], quantity="1")


def test_static_live_order_placer_get_accounts_and_portfolio():
    placer = StaticLiveOrderPlacer()
    placer.record_accounts({"results": [{"account_number": "987155785"}]})
    placer.record_portfolio("987155785", {"buying_power": "1000"})
    assert placer.get_accounts()["results"][0]["account_number"] == "987155785"
    assert placer.get_portfolio("987155785")["buying_power"] == "1000"
