"""Tests for scripts/check_order_status.py -- the read-only, one-order
lookup tool for a post-submit status that came back "unknown". Never
places an order; exercises main() directly against a fake SDK client.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.check_order_status import main  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402
from src.polymarket.us_client import PolymarketUSClient  # noqa: E402
from tests.test_polymarket_us_client import _FakeOrders, _FakeSDKClient, _order_response  # noqa: E402


def _run(monkeypatch, sdk, order_id: str) -> int:
    monkeypatch.setattr(PolymarketUSClient, "_client", lambda self: sdk)
    monkeypatch.setattr(sys, "argv", ["check_order_status.py", order_id])
    monkeypatch.setenv("POLYMARKET_VENUE", "us")
    monkeypatch.delenv("POLYMARKET_US_KEY_ID", raising=False)
    monkeypatch.delenv("POLYMARKET_US_SECRET_KEY", raising=False)
    return main()


def test_filled_order_prints_the_raw_and_parsed_fill(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    order_id = "ord-filled-1"
    sdk = _FakeSDKClient(orders=_FakeOrders(retrieve_responses={
        order_id: _order_response("ORDER_STATE_FILLED", quantity=8, cum=8, avg_px="0.55", order_id=order_id),
    }))
    rc = _run(monkeypatch, sdk, order_id)
    assert rc == 0
    out = capsys.readouterr().out
    assert "RAW ORDER RESPONSE" in out
    assert '"state": "ORDER_STATE_FILLED"' in out
    assert "STATUS: filled" in out
    assert "FILLED SHARES: 8.0" in out
    assert "AVG FILL PRICE: 0.55" in out
    assert "IS_FILL: True" in out
    assert "STATUS IS UNKNOWN" not in out


def test_unrecognized_state_prints_the_raw_response_and_the_unknown_guidance(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    order_id = "C05c9b4a-df6d-4071-8f3f-54caf6fabaad"
    sdk = _FakeSDKClient(orders=_FakeOrders(retrieve_responses={
        order_id: _order_response("ORDER_STATE_SOMETHING_NEW_WE_DONT_KNOW", quantity=8, cum=0, order_id=order_id),
    }))
    rc = _run(monkeypatch, sdk, order_id)
    assert rc == 0  # read-only reporting tool -- an unknown status is not itself a script failure
    out = capsys.readouterr().out
    assert "RAW ORDER RESPONSE" in out
    assert '"state": "ORDER_STATE_SOMETHING_NEW_WE_DONT_KNOW"' in out
    assert "STATUS: unknown" in out
    assert "IS_FILL: False" in out
    assert "RAW DETAIL: {'state': 'ORDER_STATE_SOMETHING_NEW_WE_DONT_KNOW'}" in out
    assert "STATUS IS UNKNOWN" in out
    assert "_TERMINAL_NON_FILL_STATE/_RESTING_STATES" in out


def test_lookup_failure_preserves_the_raw_error_not_a_crash(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    order_id = "does-not-exist"
    sdk = _FakeSDKClient(orders=_FakeOrders(retrieve_responses={}))  # not found -> raises
    rc = _run(monkeypatch, sdk, order_id)
    assert rc == 0
    out = capsys.readouterr().out
    assert "RAW ORDER RESPONSE" in out
    assert "FAILED:" in out  # the raw retrieve() call's own failure is shown
    assert "STATUS: unknown" in out
    assert "lookup_error" in out
    assert "STATUS IS UNKNOWN" in out


def test_never_calls_orders_create(monkeypatch, tmp_path):
    """This is a read-only tool -- it must never place, cancel, or
    otherwise mutate any order."""
    monkeypatch.chdir(tmp_path)
    order_id = "ord-1"
    orders = _FakeOrders(retrieve_responses={order_id: _order_response("ORDER_STATE_FILLED", quantity=8, cum=8, avg_px="0.55", order_id=order_id)})
    sdk = _FakeSDKClient(orders=orders)
    _run(monkeypatch, sdk, order_id)
    assert orders.create_calls == []


def test_non_us_venue_is_refused(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_order_status.py", "ord-1"])
    monkeypatch.setenv("POLYMARKET_VENUE", "international")
    rc = main()
    assert rc == 1
    assert "Polymarket US only" in capsys.readouterr().out
