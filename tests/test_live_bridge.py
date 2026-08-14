from __future__ import annotations

import pytest

from src.live_bridge import StaticHoodClient


def test_records_and_returns_equity_quotes():
    client = StaticHoodClient()
    client.record_equity_quotes("AAPL", {"data": {"results": []}})
    assert client.get_equity_quotes(["AAPL"]) == {"data": {"results": []}}


def test_raises_clear_error_when_nothing_recorded():
    client = StaticHoodClient()
    with pytest.raises(KeyError, match="get_equity_quotes"):
        client.get_equity_quotes(["AAPL"])


def test_option_instruments_keyed_by_chain_id():
    client = StaticHoodClient()
    client.record_option_instruments("chain-1", {"data": {"instruments": [{"id": "opt-1"}]}})
    assert client.get_option_instruments(chain_id="chain-1")["data"]["instruments"][0]["id"] == "opt-1"


def test_option_instruments_keyed_by_ids_string():
    client = StaticHoodClient()
    client.record_option_instruments("opt-1,opt-2", {"data": {"instruments": []}})
    result = client.get_option_instruments(ids="opt-1,opt-2")
    assert result == {"data": {"instruments": []}}


def test_option_positions_keyed_by_account_number():
    client = StaticHoodClient()
    client.record_option_positions("987155785", {"data": {"positions": []}})
    assert client.get_option_positions("987155785", nonzero=True) == {"data": {"positions": []}}


def test_client_has_no_order_placement_method():
    client = StaticHoodClient()
    order_related = {"place_option_order", "review_option_order", "cancel_option_order"}
    assert order_related.isdisjoint({m for m in dir(client) if not m.startswith("_")})
