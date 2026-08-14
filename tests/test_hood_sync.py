"""Tests for the real-Robinhood-position sync, using mocked responses
shaped like the real get_option_positions / get_option_instruments output
verified live (see hood_sync.py's module docstring)."""

from __future__ import annotations

from datetime import date

import pytest

from src.position_manager.hood_sync import HoodSyncError, sync_open_positions_from_hood

ACCOUNT = "987155785"


class _FakeClient:
    def __init__(self, positions=None, instruments=None, raise_on=None):
        self.positions = positions if positions is not None else []
        self.instruments = instruments if instruments is not None else []
        self.raise_on = raise_on or set()
        self.calls = []

    def get_option_positions(self, account_number, nonzero=None, **kwargs):
        self.calls.append("get_option_positions")
        if "get_option_positions" in self.raise_on:
            raise RuntimeError("simulated failure")
        return {"data": {"positions": self.positions}, "guide": "..."}

    def get_option_instruments(self, ids=None, **kwargs):
        self.calls.append("get_option_instruments")
        if "get_option_instruments" in self.raise_on:
            raise RuntimeError("simulated failure")
        return {"data": {"instruments": self.instruments}, "guide": "..."}


def _long_call_row(option_id="opt-1", symbol="SPY", quantity="1.0000", average_price="3.62"):
    return {
        "option_id": option_id,
        "chain_id": "chain-1",
        "chain_symbol": symbol,
        "type": "long",
        "quantity": quantity,
        "average_price": average_price,
        "expiration_date": "2026-08-21",
        "trade_value_multiplier": "100.0000",
        "opened_at": "2026-08-14T04:20:07.375316Z",
    }


def _instrument(option_id="opt-1", strike="780.0000", option_type="call"):
    return {"id": option_id, "strike_price": strike, "type": option_type}


def test_no_positions_returns_empty_result(paper_settings):
    client = _FakeClient(positions=[])
    result = sync_open_positions_from_hood(client, ACCOUNT, paper_settings)
    assert result.positions == ()
    assert result.skipped_short_count == 0


def test_zero_quantity_rows_are_excluded(paper_settings):
    client = _FakeClient(positions=[_long_call_row(quantity="0.0000")])
    result = sync_open_positions_from_hood(client, ACCOUNT, paper_settings)
    assert result.positions == ()


def test_long_call_position_syncs_correctly(paper_settings):
    client = _FakeClient(positions=[_long_call_row()], instruments=[_instrument()])
    result = sync_open_positions_from_hood(client, ACCOUNT, paper_settings)

    assert len(result.positions) == 1
    position = result.positions[0]
    assert position.symbol == "SPY"
    assert position.option_id == "opt-1"
    assert position.side == "long_call"
    assert position.quantity == 1
    assert position.entry_price == 3.62
    assert position.expiration == date(2026, 8, 21)
    assert position.thesis.direction == "bullish"
    assert position.thesis.setup_name == "synced-from-robinhood"


def test_long_put_position_maps_to_bearish_thesis(paper_settings):
    client = _FakeClient(
        positions=[_long_call_row(option_id="opt-2")],
        instruments=[_instrument(option_id="opt-2", option_type="put")],
    )
    result = sync_open_positions_from_hood(client, ACCOUNT, paper_settings)
    assert result.positions[0].side == "long_put"
    assert result.positions[0].thesis.direction == "bearish"


def test_short_positions_are_skipped_not_misrepresented(paper_settings):
    row = _long_call_row()
    row["type"] = "short"
    client = _FakeClient(positions=[row], instruments=[_instrument()])
    result = sync_open_positions_from_hood(client, ACCOUNT, paper_settings)
    assert result.positions == ()
    assert result.skipped_short_count == 1


def test_profit_target_and_stop_loss_use_configured_defaults(paper_settings):
    client = _FakeClient(positions=[_long_call_row()], instruments=[_instrument()])
    result = sync_open_positions_from_hood(client, ACCOUNT, paper_settings)
    position = result.positions[0]
    cost_basis = 3.62 * 1 * 100
    assert position.profit_target_usd == pytest.approx(cost_basis * paper_settings.synced_position_profit_target_pct)
    assert position.stop_loss_usd == pytest.approx(cost_basis * paper_settings.synced_position_stop_loss_pct)


def test_missing_instrument_lookup_is_skipped_not_fabricated(paper_settings):
    client = _FakeClient(positions=[_long_call_row()], instruments=[])  # instrument lookup fails to resolve
    result = sync_open_positions_from_hood(client, ACCOUNT, paper_settings)
    assert result.positions == ()
    assert result.skipped_unparseable_count == 1


def test_get_option_positions_tool_error_raises(paper_settings):
    client = _FakeClient(raise_on={"get_option_positions"})
    with pytest.raises(HoodSyncError):
        sync_open_positions_from_hood(client, ACCOUNT, paper_settings)


def test_get_option_instruments_tool_error_degrades_to_empty_not_raise(paper_settings):
    client = _FakeClient(positions=[_long_call_row()], raise_on={"get_option_instruments"})
    result = sync_open_positions_from_hood(client, ACCOUNT, paper_settings)
    assert result.positions == ()
    assert result.skipped_unparseable_count == 1


def test_never_calls_order_placement_methods(paper_settings):
    client = _FakeClient(positions=[_long_call_row()], instruments=[_instrument()])
    sync_open_positions_from_hood(client, ACCOUNT, paper_settings)
    order_related = {"place_option_order", "review_option_order", "cancel_option_order"}
    assert order_related.isdisjoint(set(client.calls))
    assert order_related.isdisjoint({m for m in dir(client) if not m.startswith("_")})


def test_batches_instrument_lookups_into_one_call(paper_settings):
    client = _FakeClient(
        positions=[_long_call_row(option_id="opt-1"), _long_call_row(option_id="opt-2", symbol="AAPL")],
        instruments=[_instrument(option_id="opt-1"), _instrument(option_id="opt-2")],
    )
    result = sync_open_positions_from_hood(client, ACCOUNT, paper_settings)
    assert len(result.positions) == 2
    assert client.calls.count("get_option_instruments") == 1
