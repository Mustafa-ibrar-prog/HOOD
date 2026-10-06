from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.execution.emergency_stop import EmergencyStopStore
from src.polymarket.gateway import (
    LivePolymarketGateway,
    LiveTradingDisabledError,
    PaperPolymarketGateway,
    PendingOrderNotActionableError,
    get_execution_gateway,
)
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import OrderRequest
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.settings import PolymarketSettings


def _order() -> OrderRequest:
    return OrderRequest(token_id="tok-yes", outcome="YES", side="BUY", price=0.55, size_usd=5.0, reason="test")


def _settings(**overrides) -> PolymarketSettings:
    env = dict(overrides)
    return PolymarketSettings.from_env(env=env)


def _logger(tmp_path: Path) -> PolymarketDecisionLogger:
    return PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)


class _FakePlacer:
    def __init__(self, response=None, raise_exc: Exception | None = None):
        self.response = response or {"id": "order-1", "status": "matched"}
        self.raise_exc = raise_exc
        self.calls: list[OrderRequest] = []

    def place_order(self, order: OrderRequest) -> dict:
        self.calls.append(order)
        if self.raise_exc:
            raise self.raise_exc
        return self.response


# --- Paper gateway -----------------------------------------------------------

def test_paper_gateway_simulates_a_fill(tmp_path):
    settings = _settings()
    gateway = PaperPolymarketGateway(settings, _logger(tmp_path))
    result = gateway.submit_order(_order())
    assert result.status == "simulated_fill"
    assert result.filled_price == 0.55


def test_paper_gateway_refuses_outside_paper_mode(tmp_path):
    settings = _settings(POLYMARKET_TRADING_MODE="live")
    gateway = PaperPolymarketGateway(settings, _logger(tmp_path))
    with pytest.raises(LiveTradingDisabledError):
        gateway.submit_order(_order())


def test_get_execution_gateway_returns_paper_by_default(tmp_path):
    gateway = get_execution_gateway(_settings(), _logger(tmp_path))
    assert isinstance(gateway, PaperPolymarketGateway)


# --- Live gateway construction guards ---------------------------------------

def test_live_gateway_refuses_construction_without_trading_mode_live(tmp_path):
    settings = _settings(POLYMARKET_LIVE_TRADING_CONFIRMED="true")  # trading_mode still paper
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    with pytest.raises(LiveTradingDisabledError):
        LivePolymarketGateway(settings, _logger(tmp_path), store)


def test_live_gateway_refuses_construction_without_confirmation(tmp_path):
    settings = _settings(POLYMARKET_TRADING_MODE="live")  # confirmed still false
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    with pytest.raises(LiveTradingDisabledError):
        LivePolymarketGateway(settings, _logger(tmp_path), store)


def test_get_execution_gateway_requires_pending_store_for_live(tmp_path):
    settings = _settings(POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true")
    with pytest.raises(LiveTradingDisabledError):
        get_execution_gateway(settings, _logger(tmp_path))  # no pending_store passed


# --- Live gateway: submit_order always stops at pending-approval by default --

def test_submit_order_never_calls_placer_without_auto_execute(tmp_path):
    settings = _settings(POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true")
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    placer = _FakePlacer()
    gateway = LivePolymarketGateway(settings, _logger(tmp_path), store, order_placer=placer)
    result = gateway.submit_order(_order())
    assert result.status == "awaiting_approval"
    assert placer.calls == []
    pending_id = result.extra["pending_order_id"]
    assert store.get(pending_id).status == "awaiting_approval"


def test_auto_execute_places_immediately_when_enabled_and_not_stopped(tmp_path):
    settings = _settings(
        POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true", POLYMARKET_LIVE_AUTO_EXECUTE="true",
    )
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    placer = _FakePlacer()
    stop_store = EmergencyStopStore(tmp_path / "estop.json")
    stop_store.clear(authorized_by="human:test", reason="testing")
    gateway = LivePolymarketGateway(settings, _logger(tmp_path), store, order_placer=placer, emergency_stop_store=stop_store)
    result = gateway.submit_order(_order())
    assert result.status == "placed"
    assert len(placer.calls) == 1


def test_emergency_stop_blocks_even_with_auto_execute(tmp_path):
    """Defaults to STOPPED with no file present — the single most
    important guard in this module."""
    settings = _settings(
        POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true", POLYMARKET_LIVE_AUTO_EXECUTE="true",
    )
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    placer = _FakePlacer()
    stop_store = EmergencyStopStore(tmp_path / "estop.json")  # never cleared -> defaults to stopped
    gateway = LivePolymarketGateway(settings, _logger(tmp_path), store, order_placer=placer, emergency_stop_store=stop_store)
    with pytest.raises(LiveTradingDisabledError):
        gateway.submit_order(_order())
    assert placer.calls == []


def test_no_emergency_stop_store_configured_blocks_live_placement(tmp_path):
    settings = _settings(
        POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true", POLYMARKET_LIVE_AUTO_EXECUTE="true",
    )
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    placer = _FakePlacer()
    gateway = LivePolymarketGateway(settings, _logger(tmp_path), store, order_placer=placer, emergency_stop_store=None)
    with pytest.raises(LiveTradingDisabledError):
        gateway.submit_order(_order())
    assert placer.calls == []


# --- confirm_and_place --------------------------------------------------------

def test_confirm_and_place_places_an_awaiting_approval_order(tmp_path):
    settings = _settings(POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true")
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    placer = _FakePlacer()
    stop_store = EmergencyStopStore(tmp_path / "estop.json")
    stop_store.clear(authorized_by="human:test", reason="testing")
    gateway = LivePolymarketGateway(settings, _logger(tmp_path), store, emergency_stop_store=stop_store)
    result = gateway.submit_order(_order())
    pending_id = result.extra["pending_order_id"]

    placed = gateway.confirm_and_place(pending_id, placer, approved_by="human:test")
    assert placed.status == "placed"
    assert len(placer.calls) == 1
    assert store.get(pending_id).status == "placed"


def test_confirm_and_place_refuses_expired_order(tmp_path):
    settings = _settings(POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true")
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    placer = _FakePlacer()
    stop_store = EmergencyStopStore(tmp_path / "estop.json")
    stop_store.clear(authorized_by="human:test", reason="testing")
    gateway = LivePolymarketGateway(settings, _logger(tmp_path), store, emergency_stop_store=stop_store)
    result = gateway.submit_order(_order())
    pending_id = result.extra["pending_order_id"]

    far_future = datetime.now(timezone.utc) + timedelta(days=1)
    with pytest.raises(PendingOrderNotActionableError):
        gateway.confirm_and_place(pending_id, placer, approved_by="human:test", now=far_future)
    assert placer.calls == []
    assert store.get(pending_id).status == "expired"


def test_confirm_and_place_refuses_unknown_pending_id(tmp_path):
    settings = _settings(POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true")
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    gateway = LivePolymarketGateway(settings, _logger(tmp_path), store)
    with pytest.raises(PendingOrderNotActionableError):
        gateway.confirm_and_place("does-not-exist", _FakePlacer(), approved_by="human:test")


def test_placer_failure_marks_pending_failed_and_reraises(tmp_path):
    settings = _settings(POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true")
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    placer = _FakePlacer(raise_exc=RuntimeError("network error"))
    stop_store = EmergencyStopStore(tmp_path / "estop.json")
    stop_store.clear(authorized_by="human:test", reason="testing")
    gateway = LivePolymarketGateway(settings, _logger(tmp_path), store, emergency_stop_store=stop_store)
    result = gateway.submit_order(_order())
    pending_id = result.extra["pending_order_id"]

    with pytest.raises(RuntimeError):
        gateway.confirm_and_place(pending_id, placer, approved_by="human:test")
    assert store.get(pending_id).status == "failed"


def test_reject_pending(tmp_path):
    settings = _settings(POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true")
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    gateway = LivePolymarketGateway(settings, _logger(tmp_path), store)
    result = gateway.submit_order(_order())
    pending_id = result.extra["pending_order_id"]
    rejected = gateway.reject_pending(pending_id, reason="bad price", rejected_by="human:test")
    assert rejected.status == "rejected"
    with pytest.raises(PendingOrderNotActionableError):
        gateway.reject_pending(pending_id, reason="again", rejected_by="human:test")
