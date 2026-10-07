"""Tests for scripts/reconcile_pending_orders.py -- the reconciliation-
ONLY sweep (no market discovery, no strategy, no new order ever
submitted). Exercises main() directly against a fake SDK client.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.reconcile_pending_orders import main  # noqa: E402
from src.polymarket.models import OrderRequest, PendingLiveOrder  # noqa: E402
from src.polymarket.pending import PolymarketPendingOrderStore  # noqa: E402
from src.polymarket.positions import PolymarketPositionStore  # noqa: E402
from src.polymarket.us_client import PolymarketUSClient  # noqa: E402
from tests.test_polymarket_manual_us_test import _real_now  # noqa: E402
from tests.test_polymarket_us_client import _FakeOrders, _FakeSDKClient, _NotFoundError, _order_response  # noqa: E402


def _env(tmp_path, **overrides):
    env = {
        "POLYMARKET_VENUE": "us", "POLYMARKET_US_KEY_ID": "test-key", "POLYMARKET_US_SECRET_KEY": "dGVzdA==",
        "POLYMARKET_PENDING_ORDERS_FILE": str(tmp_path / "pending.json"),
        "POLYMARKET_POSITIONS_FILE": str(tmp_path / "positions.json"),
        "POLYMARKET_DAILY_PNL_FILE": str(tmp_path / "pnl.json"),
        "POLYMARKET_DECISION_LOG_FILE": str(tmp_path / "decisions.jsonl"),
    }
    env.update(overrides)
    return env


def _seed_pending(tmp_path, *, exchange_order_id: str, condition_id="cpc-some-market") -> PendingLiveOrder:
    order = OrderRequest(
        condition_id=condition_id, token_id=condition_id, outcome="YES", side="BUY", size_usd=5.0,
        max_price=0.60, close_time=_real_now() + timedelta(minutes=5), reason="test",
    )
    pending = PendingLiveOrder.new(order=order, expiry_seconds=600)
    pending = pending.with_status("submitted", exchange_order_id=exchange_order_id)
    PolymarketPendingOrderStore(tmp_path / "pending.json").add(pending)
    return pending


def _run(monkeypatch, tmp_path, sdk, **env_overrides) -> int:
    monkeypatch.setattr(PolymarketUSClient, "_client", lambda self: sdk)
    monkeypatch.setattr(sys, "argv", ["reconcile_pending_orders.py"])
    for key, value in _env(tmp_path, **env_overrides).items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(tmp_path)
    return main()


def test_nothing_to_reconcile_is_a_clean_noop(monkeypatch, tmp_path, capsys):
    sdk = _FakeSDKClient(orders=_FakeOrders())
    rc = _run(monkeypatch, tmp_path, sdk)
    assert rc == 0
    assert "Nothing to reconcile" in capsys.readouterr().out
    assert sdk.orders.create_calls == []


def test_resolves_a_previously_unknown_order_to_a_real_fill(monkeypatch, tmp_path, capsys):
    """The exact real scenario: a pending order left fill_reconciled=False
    after an earlier "unknown" result; running this script alone (no
    bot cycle, no discovery, no new order) picks it up and correctly
    opens the position now that the exchange shows a real fill."""
    order_id = "CZ510YB5PYWT"
    market_slug = "cpc-btc-updown-15m-2026-10-07-2230z"
    _seed_pending(tmp_path, exchange_order_id=order_id, condition_id=market_slug)
    sdk = _FakeSDKClient(orders=_FakeOrders(retrieve_responses={
        order_id: _order_response("ORDER_STATE_FILLED", quantity=5, cum=5, avg_px="0.36", order_id=order_id),
    }))

    rc = _run(monkeypatch, tmp_path, sdk)

    assert rc == 0
    out = capsys.readouterr().out
    assert "Unreconciled pending orders found: 1" in out
    assert "RECONCILED" in out
    assert "Open positions now: 1" in out
    assert sdk.orders.create_calls == []  # never places anything
    positions = PolymarketPositionStore(tmp_path / "positions.json").load()
    assert len(positions) == 1
    assert positions[0].filled_shares == 5.0
    assert positions[0].avg_fill_price == 0.36


def test_still_unknown_leaves_it_for_a_later_sweep(monkeypatch, tmp_path, capsys):
    order_id = "ord-still-unknown"
    _seed_pending(tmp_path, exchange_order_id=order_id)
    sdk = _FakeSDKClient(orders=_FakeOrders(retrieve_responses={}))  # still 404s

    rc = _run(monkeypatch, tmp_path, sdk)

    assert rc == 0
    out = capsys.readouterr().out
    assert "STILL UNKNOWN" in out
    assert "Open positions now: 0" in out
    assert sdk.orders.create_calls == []


def test_never_touches_an_already_reconciled_order(monkeypatch, tmp_path, capsys):
    order_id = "ord-done"
    pending = _seed_pending(tmp_path, exchange_order_id=order_id)
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    done = store.get(pending.id).with_status("submitted", fill_reconciled=True)
    store.update(done)
    sdk = _FakeSDKClient(orders=_FakeOrders())

    rc = _run(monkeypatch, tmp_path, sdk)

    assert rc == 0
    assert "Nothing to reconcile" in capsys.readouterr().out
    assert sdk.orders.retrieve_calls == []  # already reconciled -- never even re-queried
