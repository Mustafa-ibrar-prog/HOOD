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
from src.polymarket.models import OrderRequest, SubmissionOutcome
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.settings import PolymarketSettings

_VALID_KEY = "0x" + "a" * 64


def _order(**overrides) -> OrderRequest:
    now = datetime.now(timezone.utc)
    defaults = dict(
        condition_id="cond-1", token_id="tok-yes", outcome="YES", side="BUY", size_usd=5.0,
        max_price=0.55, close_time=now + timedelta(minutes=10), reason="test",
    )
    defaults.update(overrides)
    return OrderRequest(**defaults)


def _settings(**overrides) -> PolymarketSettings:
    env = dict(overrides)
    return PolymarketSettings.from_env(env=env)


def _logger(tmp_path: Path) -> PolymarketDecisionLogger:
    return PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)


class _FakePlacer:
    def __init__(self, outcome: SubmissionOutcome | None = None, raise_exc: Exception | None = None):
        self.outcome = outcome or SubmissionOutcome(ok=True, exchange_order_id="ex-1", raw_status="matched")
        self.raise_exc = raise_exc
        self.calls: list[OrderRequest] = []

    def place_order(self, order: OrderRequest) -> SubmissionOutcome:
        self.calls.append(order)
        if self.raise_exc:
            raise self.raise_exc
        return self.outcome


# --- Paper gateway -----------------------------------------------------------

def test_paper_gateway_simulates_a_fill(tmp_path):
    settings = _settings()
    gateway = PaperPolymarketGateway(settings, _logger(tmp_path))
    result = gateway.submit_order(_order())
    assert result.status == "simulated_fill"
    assert result.fill_result is not None
    assert result.fill_result.is_fill
    assert result.fill_result.avg_fill_price == 0.55
    assert result.submission is None  # nothing was ever submitted to an exchange


def test_paper_gateway_uses_explicit_quantity_for_a_sell_exit(tmp_path):
    """A SELL (exit) order carries an exact share count -- the paper
    simulation must honor it verbatim, never re-derive shares from
    size_usd/max_price (that reconstruction is unsafe for a SELL -- see
    OrderRequest.quantity's docstring)."""
    settings = _settings()
    gateway = PaperPolymarketGateway(settings, _logger(tmp_path))
    order = _order(side="SELL", size_usd=2.16, max_price=0.432, quantity=5)
    result = gateway.submit_order(order)
    assert result.status == "simulated_fill"
    assert result.fill_result.filled_shares == 5
    assert result.fill_result.requested_shares == 5
    assert result.fill_result.avg_fill_price == 0.432


def test_paper_gateway_buy_still_derives_shares_from_size_and_price(tmp_path):
    """Unchanged BUY behavior: no `quantity` set, shares still come
    from size_usd/max_price exactly as before this feature."""
    settings = _settings()
    gateway = PaperPolymarketGateway(settings, _logger(tmp_path))
    result = gateway.submit_order(_order(size_usd=5.0, max_price=0.5))
    assert result.fill_result.filled_shares == pytest.approx(10.0)


def test_paper_gateway_refuses_outside_paper_mode(tmp_path):
    settings = _settings(POLYMARKET_TRADING_MODE="live", POLYMARKET_PRIVATE_KEY=_VALID_KEY)
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
    settings = _settings(POLYMARKET_TRADING_MODE="live", POLYMARKET_PRIVATE_KEY=_VALID_KEY)  # confirmed still false
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    with pytest.raises(LiveTradingDisabledError):
        LivePolymarketGateway(settings, _logger(tmp_path), store)


def test_get_execution_gateway_requires_pending_store_for_live(tmp_path):
    settings = _settings(
        POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true", POLYMARKET_PRIVATE_KEY=_VALID_KEY,
    )
    with pytest.raises(LiveTradingDisabledError):
        get_execution_gateway(settings, _logger(tmp_path))  # no pending_store passed


# --- Live gateway: submit_order always stops at pending-approval by default --

def test_submit_order_never_calls_placer_without_auto_execute(tmp_path):
    settings = _settings(
        POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true", POLYMARKET_PRIVATE_KEY=_VALID_KEY,
    )
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    placer = _FakePlacer()
    gateway = LivePolymarketGateway(settings, _logger(tmp_path), store, order_placer=placer)
    result = gateway.submit_order(_order())
    assert result.status == "awaiting_approval"
    assert placer.calls == []
    pending_id = result.extra["pending_order_id"]
    assert store.get(pending_id).status == "awaiting_approval"
    assert store.get(pending_id).fill_reconciled is False


def test_auto_execute_places_immediately_when_enabled_and_not_stopped(tmp_path):
    settings = _settings(
        POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true", POLYMARKET_LIVE_AUTO_EXECUTE="true",
        POLYMARKET_PRIVATE_KEY=_VALID_KEY,
    )
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    placer = _FakePlacer()
    stop_store = EmergencyStopStore(tmp_path / "estop.json")
    stop_store.clear(authorized_by="human:test", reason="testing")
    gateway = LivePolymarketGateway(settings, _logger(tmp_path), store, order_placer=placer, emergency_stop_store=stop_store)
    result = gateway.submit_order(_order())
    assert result.status == "submitted"  # SUBMITTED, not filled — gateway.py never determines fills
    assert result.fill_result is None
    assert result.submission is not None and result.submission.exchange_order_id == "ex-1"
    assert len(placer.calls) == 1
    pending_id = result.extra["pending_order_id"]
    assert store.get(pending_id).fill_reconciled is False  # left for reconciliation.py


def test_emergency_stop_blocks_even_with_auto_execute(tmp_path):
    """Defaults to STOPPED with no file present — the single most
    important guard in this module."""
    settings = _settings(
        POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true", POLYMARKET_LIVE_AUTO_EXECUTE="true",
        POLYMARKET_PRIVATE_KEY=_VALID_KEY,
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
        POLYMARKET_PRIVATE_KEY=_VALID_KEY,
    )
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    placer = _FakePlacer()
    gateway = LivePolymarketGateway(settings, _logger(tmp_path), store, order_placer=placer, emergency_stop_store=None)
    with pytest.raises(LiveTradingDisabledError):
        gateway.submit_order(_order())
    assert placer.calls == []


# --- confirm_and_place ---------------------------------------------------------

def test_confirm_and_place_submits_an_awaiting_approval_order(tmp_path):
    settings = _settings(POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true", POLYMARKET_PRIVATE_KEY=_VALID_KEY)
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    placer = _FakePlacer()
    stop_store = EmergencyStopStore(tmp_path / "estop.json")
    stop_store.clear(authorized_by="human:test", reason="testing")
    gateway = LivePolymarketGateway(settings, _logger(tmp_path), store, emergency_stop_store=stop_store)
    result = gateway.submit_order(_order())
    pending_id = result.extra["pending_order_id"]

    submitted = gateway.confirm_and_place(pending_id, placer, approved_by="human:test")
    assert submitted.status == "submitted"
    assert submitted.fill_result is None  # confirm_and_place() never determines a fill
    assert len(placer.calls) == 1
    pending = store.get(pending_id)
    assert pending.status == "submitted"
    assert pending.exchange_order_id == "ex-1"
    assert pending.fill_reconciled is False


def test_confirm_and_place_refuses_expired_order(tmp_path):
    settings = _settings(POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true", POLYMARKET_PRIVATE_KEY=_VALID_KEY)
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
    settings = _settings(POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true", POLYMARKET_PRIVATE_KEY=_VALID_KEY)
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    gateway = LivePolymarketGateway(settings, _logger(tmp_path), store)
    with pytest.raises(PendingOrderNotActionableError):
        gateway.confirm_and_place("does-not-exist", _FakePlacer(), approved_by="human:test")


def test_placer_failure_marks_pending_failed_and_reraises(tmp_path):
    settings = _settings(POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true", POLYMARKET_PRIVATE_KEY=_VALID_KEY)
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


def test_exchange_rejection_marks_pending_rejected_and_fill_reconciled(tmp_path):
    """A clean rejection FROM the exchange (not an exception, e.g.
    fok_not_filled) has no exchange_order_id — there is nothing for
    reconciliation.py to look up, so gateway.py marks it
    fill_reconciled=True immediately, rather than leaving a rejected
    order to be swept forever."""
    settings = _settings(POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true", POLYMARKET_PRIVATE_KEY=_VALID_KEY)
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    rejection = SubmissionOutcome(ok=False, exchange_order_id=None, raw_status=None, error_code="fok_not_filled", error_message="no match")
    placer = _FakePlacer(outcome=rejection)
    stop_store = EmergencyStopStore(tmp_path / "estop.json")
    stop_store.clear(authorized_by="human:test", reason="testing")
    gateway = LivePolymarketGateway(settings, _logger(tmp_path), store, emergency_stop_store=stop_store)
    result = gateway.submit_order(_order())
    pending_id = result.extra["pending_order_id"]

    outcome_result = gateway.confirm_and_place(pending_id, placer, approved_by="human:test")
    assert outcome_result.status == "rejected"
    pending = store.get(pending_id)
    assert pending.status == "rejected"
    assert pending.exchange_order_id is None
    assert pending.fill_reconciled is True  # nothing to reconcile


def test_reject_pending(tmp_path):
    settings = _settings(POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true", POLYMARKET_PRIVATE_KEY=_VALID_KEY)
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    gateway = LivePolymarketGateway(settings, _logger(tmp_path), store)
    result = gateway.submit_order(_order())
    pending_id = result.extra["pending_order_id"]
    rejected = gateway.reject_pending(pending_id, reason="bad price", rejected_by="human:test")
    assert rejected.status == "rejected"
    assert rejected.fill_reconciled is True
    with pytest.raises(PendingOrderNotActionableError):
        gateway.reject_pending(pending_id, reason="again", rejected_by="human:test")
