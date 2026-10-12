"""Tests for scripts/check_order_status.py -- the read-only investigation
tool for an already-submitted order whose post-submit status came back
"unknown". Exercises main() directly against a fake SDK client; never
places, cancels, or modifies anything.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.check_order_status import main  # noqa: E402
from src.polymarket.us_client import PolymarketUSClient  # noqa: E402
from tests.test_polymarket_us_client import (  # noqa: E402
    _FakeOrders,
    _FakePortfolio,
    _FakeSDKClient,
    _order_response,
)


def _run(monkeypatch, sdk, order_id: str, *, market_slug: str | None = None) -> int:
    argv = ["check_order_status.py", order_id]
    if market_slug:
        argv += ["--market-slug", market_slug]
    monkeypatch.setattr(PolymarketUSClient, "_client", lambda self: sdk)
    monkeypatch.setattr(sys, "argv", argv)
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
    assert "STATUS REMAINS UNKNOWN" not in out


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


# --- The real incident: create -> retrieve NotFoundError, with evidence -----
# gathered from orders.list()/portfolio.activities()/portfolio.positions()
# too -- never inferring FILLED/CANCELED/REJECTED/EXPIRED from the 404 alone.

def test_retrieve_not_found_with_no_evidence_anywhere_stays_unknown(monkeypatch, tmp_path, capsys):
    """Regression for the exact real incident: orders.retrieve() 404s,
    the order appears in NONE of orders.list()/portfolio.activities()/
    portfolio.positions() either. The tool must still report STATUS:
    unknown -- not infer cancellation/rejection/expiry just because
    no source shows the order -- and must print all four sections so
    a human can review them directly."""
    order_id = "C05c9b4a-df6d-4071-8f3f-54caf6fabaad"
    market_slug = "cpc-btc-updown-15m-2026-10-07-2145z"
    sdk = _FakeSDKClient(
        orders=_FakeOrders(retrieve_responses={}, list_response={"orders": []}),  # 404s; no open orders either
        portfolio=_FakePortfolio(activities_response={"activities": []}, positions_response={"positions": {}}),
    )
    monkeypatch.chdir(tmp_path)
    rc = _run(monkeypatch, sdk, order_id, market_slug=market_slug)

    assert rc == 0
    out = capsys.readouterr().out
    assert "1. RAW ORDER RESPONSE" in out
    assert "FAILED:" in out  # orders.retrieve()'s own 404
    assert "STATUS: unknown" in out
    assert "lookup_error" in out
    assert "2. OPEN ORDERS" in out
    assert "3. ACCOUNT ACTIVITY" in out
    assert "4. CURRENT POSITIONS" in out
    assert "STATUS REMAINS UNKNOWN" in out
    # Never claims a terminal determination anywhere in the output.
    for forbidden in ("STATUS: filled", "STATUS: cancelled", "STATUS: rejected", "STATUS: expired"):
        assert forbidden not in out
    assert sdk.orders.list_calls == [{"slugs": [market_slug]}]
    assert sdk.portfolio.activities_calls == [{"marketSlug": market_slug}]
    assert sdk.portfolio.positions_calls == [{"market": market_slug}]


def test_open_orders_shows_the_order_if_it_is_still_resting(monkeypatch, tmp_path, capsys):
    order_id = "ord-resting-1"
    market_slug = "cpc-some-market"
    sdk = _FakeSDKClient(
        orders=_FakeOrders(
            retrieve_responses={order_id: _order_response("ORDER_STATE_NEW", quantity=8, cum=0, order_id=order_id)},
            list_response={"orders": [{"id": order_id, "marketSlug": market_slug, "state": "ORDER_STATE_NEW"}]},
        ),
    )
    monkeypatch.chdir(tmp_path)
    rc = _run(monkeypatch, sdk, order_id, market_slug=market_slug)
    assert rc == 0
    out = capsys.readouterr().out
    assert "2. OPEN ORDERS" in out
    assert order_id in out  # the order's own id is visible in the dumped open-orders list
    assert "STATUS: resting" in out


def test_activities_shows_a_trade_for_the_market_even_though_retrieve_404s(monkeypatch, tmp_path, capsys):
    """If orders.retrieve() 404s but portfolio.activities() shows a real
    trade for this market, that evidence must still be printed in full
    -- this script draws no conclusion, but a human reading section 3
    can see it."""
    order_id = "ord-ghost-1"
    market_slug = "cpc-some-market"
    trade_activity = {
        "type": "ACTIVITY_TYPE_TRADE",
        "trade": {"id": "trade-1", "marketSlug": market_slug, "state": "FILLED", "qty": "8", "price": {"value": "0.55", "currency": "USD"}},
    }
    sdk = _FakeSDKClient(
        orders=_FakeOrders(retrieve_responses={}),
        portfolio=_FakePortfolio(activities_response={"activities": [trade_activity]}),
    )
    monkeypatch.chdir(tmp_path)
    rc = _run(monkeypatch, sdk, order_id, market_slug=market_slug)
    assert rc == 0
    out = capsys.readouterr().out
    assert "3. ACCOUNT ACTIVITY" in out
    assert "ACTIVITY_TYPE_TRADE" in out
    assert "trade-1" in out
    assert "STATUS: unknown" in out  # still not inferred from orders.retrieve() alone -- section 1's own answer


def test_positions_shows_a_nonzero_position_for_the_market(monkeypatch, tmp_path, capsys):
    order_id = "ord-ghost-2"
    market_slug = "cpc-some-market"
    sdk = _FakeSDKClient(
        orders=_FakeOrders(retrieve_responses={}),
        portfolio=_FakePortfolio(positions_response={"positions": {market_slug: {"netPosition": "8", "avgPx": {"value": "0.55", "currency": "USD"}}}}),
    )
    monkeypatch.chdir(tmp_path)
    rc = _run(monkeypatch, sdk, order_id, market_slug=market_slug)
    assert rc == 0
    out = capsys.readouterr().out
    assert "4. CURRENT POSITIONS" in out
    assert '"netPosition": "8"' in out


def test_without_market_slug_still_runs_and_suggests_providing_one(monkeypatch, tmp_path, capsys):
    order_id = "ord-1"
    sdk = _FakeSDKClient(orders=_FakeOrders(retrieve_responses={}))
    monkeypatch.chdir(tmp_path)
    rc = _run(monkeypatch, sdk, order_id)  # no market_slug
    assert rc == 0
    out = capsys.readouterr().out
    assert "Re-run with --market-slug" in out
    assert sdk.orders.list_calls == [None]
    assert sdk.portfolio.activities_calls == [None]
    assert sdk.portfolio.positions_calls == [None]
