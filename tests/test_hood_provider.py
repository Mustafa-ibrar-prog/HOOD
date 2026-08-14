"""Tests for HoodMarketDataProvider, using a fake HoodToolClient built from
mocked responses shaped like the REAL HOOD MCP tools' output — verified via
live, read-only calls (SPY underlying; a SPY $780 call expiring 2026-08-21
as the option contract). No real network call, no real MCP tool call, and
— critically — no order-placement method exists anywhere on the fake
client or the Protocol it implements.

See tests/test_hood_provider_real_shapes.py for regression tests built
directly from the captured real payloads (not this file's synthesized
happy-path fixtures).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.market.errors import (
    HoodToolError,
    InvalidQuoteError,
    MarketDataError,
    OptionContractNotFoundError,
    QuoteUnavailableError,
)
from src.market.hood_client import HoodToolClient
from src.market.hood_provider import HoodMarketDataProvider

UNDERLYING = "AAPL"
OPTION_ID = "11111111-1111-1111-1111-111111111111"


def _bar(minutes_ago: int, close: float, volume: int | None = 1000, interpolated: bool = False, now=None):
    """Shaped like a real historicals bar: begins_at/open_price/high_price/
    low_price/close_price. volume=None omits the field entirely, matching
    real option bars (which carry no volume field at all)."""
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(minutes=minutes_ago)
    bar = {
        "begins_at": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "open_price": f"{close - 0.05:.4f}",
        "high_price": f"{close + 0.05:.4f}",
        "low_price": f"{close - 0.10:.4f}",
        "close_price": f"{close:.4f}",
        "session": "reg",
    }
    if volume is not None:
        bar["volume"] = volume
    if interpolated:
        bar["interpolated"] = True
    return bar


def _equity_quote_row(
    symbol="AAPL",
    last_trade_price="231.00",
    previous_close="228.00",
    as_of=None,
    has_traded=True,
    state="active",
):
    as_of = as_of or datetime.now(timezone.utc)
    return {
        "quote": {
            "symbol": symbol,
            "last_trade_price": last_trade_price,
            "venue_last_trade_time": as_of.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "last_non_reg_trade_price": None,
            "venue_last_non_reg_trade_time": None,
            "adjusted_previous_close": previous_close,
            "previous_close": previous_close,
            "previous_close_date": "2026-08-13",
            "bid_price": "230.98",
            "ask_price": "231.02",
            "has_traded": has_traded,
            "state": state,
        },
        "close": {"symbol": symbol, "date": "2026-08-13", "price": previous_close, "interpolated": False, "source": "sip-list-exchange-close"},
    }


def _option_quote_row(
    instrument_id=OPTION_ID,
    bid_price="1.03",
    ask_price="1.07",
    mark_price="1.05",
    previous_close_price="0.90",
    volume=500,
    open_interest=1000,
    updated_at=None,
):
    updated_at = updated_at or datetime.now(timezone.utc)
    return {
        "quote": {
            "instrument_id": instrument_id,
            "ask_price": ask_price,
            "ask_size": 10,
            "bid_price": bid_price,
            "bid_size": 10,
            "mark_price": mark_price,
            "adjusted_mark_price": mark_price,
            "previous_close_price": previous_close_price,
            "previous_close_date": "2026-08-13",
            "implied_volatility": "0.20",
            "delta": "0.45",
            "open_interest": open_interest,
            "volume": volume,
            "updated_at": updated_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        },
        "close": {"instrument_id": instrument_id, "symbol": UNDERLYING, "date": "2026-08-13", "price": previous_close_price, "interpolated": False, "source": "ddb-market-snapshot"},
    }


class FakeHoodToolClient:
    """Implements HoodToolClient with entirely canned, mocked responses
    shaped like the real tools. Never touches a network, an MCP tool, or
    an order-placement endpoint — there is no such method to call."""

    def __init__(
        self,
        *,
        equity_quote_rows=None,
        option_quote_rows=None,
        equity_bars=None,
        option_bars=None,
        chains=None,
        instruments=None,
        raise_on=None,
    ):
        self.equity_quote_rows = equity_quote_rows
        self.option_quote_rows = option_quote_rows
        self.equity_bars = equity_bars if equity_bars is not None else []
        self.option_bars = option_bars if option_bars is not None else []
        self.chains = chains if chains is not None else []
        self.instruments = instruments if instruments is not None else []
        self.raise_on = raise_on or set()
        self.calls: list[str] = []

    def _maybe_raise(self, name):
        self.calls.append(name)
        if name in self.raise_on:
            raise RuntimeError(f"simulated upstream failure in {name}")

    def get_equity_quotes(self, symbols):
        self._maybe_raise("get_equity_quotes")
        return {"data": {"results": self.equity_quote_rows}, "guide": "..."}

    def get_option_quotes(self, instrument_ids):
        self._maybe_raise("get_option_quotes")
        return {"data": {"results": self.option_quote_rows}, "guide": "..."}

    def get_equity_historicals(self, symbols, start_time, end_time=None, interval=None, bounds=None, adjustment_type=None):
        self._maybe_raise("get_equity_historicals")
        return {"data": {"results": [{"symbol": symbols[0], "interval": "5minute", "bounds": "regular", "bars": self.equity_bars}]}, "guide": "..."}

    def get_option_historicals(self, instrument_ids, start_time, end_time=None, interval=None, bounds=None):
        self._maybe_raise("get_option_historicals")
        return {"data": {"results": [{"instrument_id": instrument_ids[0], "interval": "5minute", "bounds": "regular", "bars": self.option_bars}]}, "guide": "..."}

    def get_option_chains(self, underlying_symbol=None, ids=None):
        self._maybe_raise("get_option_chains")
        return {"data": {"chains": self.chains}, "guide": "..."}

    def get_option_instruments(self, chain_symbol=None, chain_id=None, ids=None, expiration_dates=None, strike_price=None, type=None, state=None, tradability=None, cursor=None):
        self._maybe_raise("get_option_instruments")
        return {"data": {"instruments": self.instruments}, "guide": "..."}


def _happy_client(now: datetime, **overrides) -> FakeHoodToolClient:
    closes = [228.0, 229.0, 229.5, 230.2, 230.8, 231.0]
    equity_bars = [_bar(minutes_ago=(len(closes) - i) * 5, close=c, now=now) for i, c in enumerate(closes)]
    option_bars = [_bar(minutes_ago=(len(closes) - i) * 5, close=c, volume=None, now=now) for i, c in enumerate(closes)]
    defaults = dict(
        equity_quote_rows=[_equity_quote_row(as_of=now)],
        option_quote_rows=[_option_quote_row(updated_at=now)],
        equity_bars=equity_bars,
        option_bars=option_bars,
    )
    defaults.update(overrides)
    return FakeHoodToolClient(**defaults)


@pytest.fixture
def now() -> datetime:
    # A Tuesday, well inside regular market hours in US/Eastern.
    return datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc)  # 11:00 ET


def test_client_protocol_has_no_order_placement_method():
    order_related = {"place_option_order", "review_option_order", "cancel_option_order", "place_equity_order"}
    protocol_methods = set(HoodToolClient.__protocol_attrs__) if hasattr(HoodToolClient, "__protocol_attrs__") else {
        name for name in dir(HoodToolClient) if not name.startswith("_")
    }
    assert order_related.isdisjoint(protocol_methods)
    assert order_related.isdisjoint(set(dir(FakeHoodToolClient)))


def test_happy_path_assembles_full_snapshot(paper_settings, now):
    client = _happy_client(now)
    provider = HoodMarketDataProvider(client, paper_settings)

    snapshot = provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)

    assert snapshot.underlying.symbol == "AAPL"
    assert snapshot.underlying.last_trade_price == 231.00
    assert snapshot.option.bid_price == 1.03
    assert snapshot.option.ask_price == 1.07
    assert snapshot.option.last_trade_price == 1.05  # mark_price
    assert snapshot.option.volume == 500
    assert snapshot.option.open_interest == 1000
    assert len(snapshot.underlying_bars) == 6
    assert len(snapshot.option_bars) == 6
    assert all(b.volume == 0 for b in snapshot.option_bars)  # option bars carry no volume
    # Computed locally from real fetched closes, not fabricated:
    assert snapshot.ema_fast is not None
    assert snapshot.ema_slow is not None
    assert snapshot.rsi is not None
    assert snapshot.vwap is not None
    assert snapshot.volume_ratio is not None
    assert snapshot.fetched_at <= now  # conservative: quote-timestamp-derived, never later than fetch


def test_calls_only_read_only_tools_never_order_tools(paper_settings, now):
    client = _happy_client(now)
    provider = HoodMarketDataProvider(client, paper_settings)
    provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)

    assert set(client.calls) <= {
        "get_equity_quotes",
        "get_option_quotes",
        "get_equity_historicals",
        "get_option_historicals",
    }
    assert "get_equity_quotes" in client.calls
    assert "get_option_quotes" in client.calls


def test_missing_equity_quote_raises_quote_unavailable(paper_settings, now):
    client = _happy_client(now, equity_quote_rows=[])
    provider = HoodMarketDataProvider(client, paper_settings)
    with pytest.raises(QuoteUnavailableError):
        provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)


def test_missing_option_quote_raises_contract_not_found(paper_settings, now):
    client = _happy_client(now, option_quote_rows=[])
    provider = HoodMarketDataProvider(client, paper_settings)
    with pytest.raises(OptionContractNotFoundError):
        provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)


def test_equity_quote_not_active_raises_quote_unavailable(paper_settings, now):
    client = _happy_client(now, equity_quote_rows=[_equity_quote_row(as_of=now, has_traded=True, state="halted")])
    provider = HoodMarketDataProvider(client, paper_settings)
    with pytest.raises(QuoteUnavailableError):
        provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)


def test_equity_quote_never_traded_raises_quote_unavailable(paper_settings, now):
    client = _happy_client(now, equity_quote_rows=[_equity_quote_row(as_of=now, has_traded=False)])
    provider = HoodMarketDataProvider(client, paper_settings)
    with pytest.raises(QuoteUnavailableError):
        provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)


def test_negative_price_quote_raises_invalid_quote(paper_settings, now):
    client = _happy_client(now, option_quote_rows=[_option_quote_row(bid_price="-1.00", updated_at=now)])
    provider = HoodMarketDataProvider(client, paper_settings)
    with pytest.raises(InvalidQuoteError):
        provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)


def test_wide_spread_quote_is_still_returned_not_rejected(paper_settings, now):
    """The provider's job is to report reality, not to enforce risk
    policy — spread gating stays in RiskManager, unchanged."""
    client = _happy_client(now, option_quote_rows=[_option_quote_row(bid_price="0.50", ask_price="1.50", mark_price="1.00", updated_at=now)])
    provider = HoodMarketDataProvider(client, paper_settings)
    snapshot = provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)
    assert snapshot.option.spread_pct > 0.5


def test_equity_quote_tool_error_raises_hood_tool_error(paper_settings, now):
    client = _happy_client(now, raise_on={"get_equity_quotes"})
    provider = HoodMarketDataProvider(client, paper_settings)
    with pytest.raises(HoodToolError):
        provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)


def test_option_quote_tool_error_raises_hood_tool_error(paper_settings, now):
    client = _happy_client(now, raise_on={"get_option_quotes"})
    provider = HoodMarketDataProvider(client, paper_settings)
    with pytest.raises(HoodToolError):
        provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)


def test_all_market_data_errors_are_a_common_base_class(paper_settings, now):
    """So callers (PositionMonitor) can catch one type and always land on
    a safe HOLD, regardless of which specific thing went wrong."""
    for client in [
        _happy_client(now, equity_quote_rows=[]),
        _happy_client(now, option_quote_rows=[]),
        _happy_client(now, raise_on={"get_equity_quotes"}),
    ]:
        provider = HoodMarketDataProvider(client, paper_settings)
        with pytest.raises(MarketDataError):
            provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)


def test_equity_bars_tool_error_degrades_gracefully(paper_settings, now):
    """Historicals are supplementary — a failure there must not prevent a
    snapshot from being returned; it just means less momentum evidence."""
    client = _happy_client(now, raise_on={"get_equity_historicals"})
    provider = HoodMarketDataProvider(client, paper_settings)
    snapshot = provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)
    assert snapshot.underlying_bars == ()
    assert snapshot.rsi is None
    assert snapshot.ema_fast is None
    assert snapshot.vwap is None
    # Critical data is unaffected:
    assert snapshot.underlying.last_trade_price == 231.00


def test_option_bars_tool_error_degrades_gracefully(paper_settings, now):
    client = _happy_client(now, raise_on={"get_option_historicals"})
    provider = HoodMarketDataProvider(client, paper_settings)
    snapshot = provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)
    assert snapshot.option_bars == ()
    assert snapshot.option.bid_price == 1.03  # critical data unaffected


def test_malformed_bars_response_degrades_gracefully_instead_of_raising(paper_settings, now):
    client = _happy_client(now)
    client.equity_bars = "not-a-list-of-bars"  # bypass the constructor's list default
    provider = HoodMarketDataProvider(client, paper_settings)
    snapshot = provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)
    assert snapshot.underlying_bars == ()


def test_interpolated_bars_are_filtered_out(paper_settings, now):
    bars = [_bar(minutes_ago=15, close=228.0, now=now), _bar(minutes_ago=10, close=229.0, interpolated=True, now=now), _bar(minutes_ago=5, close=230.0, now=now)]
    client = _happy_client(now, equity_bars=bars)
    provider = HoodMarketDataProvider(client, paper_settings)
    snapshot = provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)
    assert len(snapshot.underlying_bars) == 2
    assert all(not b.interpolated for b in snapshot.underlying_bars)


def test_bar_missing_ohlc_field_is_skipped_not_fabricated(paper_settings, now):
    bars = [
        _bar(minutes_ago=10, close=228.0, now=now),
        {**_bar(minutes_ago=5, close=229.0, now=now), "close_price": None},  # unusable row
    ]
    client = _happy_client(now, equity_bars=bars)
    provider = HoodMarketDataProvider(client, paper_settings)
    snapshot = provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)
    assert len(snapshot.underlying_bars) == 1


def test_option_bars_have_zero_volume_not_fabricated(paper_settings, now):
    """Real option bars carry no volume field at all; the provider must
    not invent a nonzero number for it."""
    client = _happy_client(now)
    provider = HoodMarketDataProvider(client, paper_settings)
    snapshot = provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)
    assert all(b.volume == 0 for b in snapshot.option_bars)


def test_too_few_bars_yields_none_indicators_not_a_crash(paper_settings, now):
    client = _happy_client(now, equity_bars=[], option_bars=[])
    provider = HoodMarketDataProvider(client, paper_settings)
    snapshot = provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)
    assert snapshot.rsi is None
    assert snapshot.macd_histogram is None
    assert snapshot.ema_fast is None
    assert snapshot.vwap is None
    assert snapshot.volume_ratio is None


def test_market_closed_logs_warning_but_still_returns_snapshot(paper_settings):
    saturday = datetime(2026, 8, 15, 15, 0, tzinfo=timezone.utc)
    client = _happy_client(saturday)
    provider = HoodMarketDataProvider(client, paper_settings)
    snapshot = provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=saturday)
    assert snapshot is not None  # informational only — does not raise or block


def test_missing_previous_close_falls_back_through_layers(paper_settings, now):
    row = _equity_quote_row(as_of=now, previous_close=None)
    row["quote"]["previous_close"] = None
    row["quote"]["adjusted_previous_close"] = None
    row["close"] = None
    client = _happy_client(now, equity_quote_rows=[row])
    provider = HoodMarketDataProvider(client, paper_settings)
    snapshot = provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)
    assert snapshot.underlying.previous_close is None


def test_equity_quote_prefers_the_more_recently_timestamped_price(paper_settings, now):
    """Mirrors get_equity_quotes' own documented guidance: pick whichever
    of last_trade_price / last_non_reg_trade_price is actually more
    recent, not always the regular-session one."""
    row = _equity_quote_row(as_of=now - timedelta(hours=1), last_trade_price="231.00")
    row["quote"]["last_non_reg_trade_price"] = "232.50"
    row["quote"]["venue_last_non_reg_trade_time"] = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")  # more recent
    client = _happy_client(now, equity_quote_rows=[row])
    provider = HoodMarketDataProvider(client, paper_settings)
    snapshot = provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)
    assert snapshot.underlying.last_trade_price == 232.50


def test_fetched_at_uses_older_of_fetch_time_and_quote_timestamps(paper_settings, now):
    """A quote that Robinhood itself hasn't refreshed in a while must be
    reflected as stale even though our own tool call just returned."""
    stale_quote_time = now - timedelta(minutes=10)
    client = _happy_client(now, equity_quote_rows=[_equity_quote_row(as_of=stale_quote_time)])
    provider = HoodMarketDataProvider(client, paper_settings)
    snapshot = provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)
    assert snapshot.fetched_at <= stale_quote_time + timedelta(seconds=1)


# --- get_option_chain_candidates -----------------------------------------------------------


def test_option_chain_candidates_happy_path(paper_settings, now):
    client = _happy_client(
        now,
        chains=[{"id": "chain-1", "symbol": "AAPL"}],
        instruments=[{"id": "opt-a", "strike_price": "230.0000", "type": "call"}],
    )
    provider = HoodMarketDataProvider(client, paper_settings)
    candidates = provider.get_option_chain_candidates("AAPL")
    assert candidates == [{"id": "opt-a", "strike_price": "230.0000", "type": "call"}]


def test_option_chain_candidates_empty_when_no_chain_found(paper_settings, now):
    client = _happy_client(now, chains=[])
    provider = HoodMarketDataProvider(client, paper_settings)
    assert provider.get_option_chain_candidates("ZZZZ") == []


def test_option_chain_candidates_raises_on_chains_tool_error(paper_settings, now):
    client = _happy_client(now, raise_on={"get_option_chains"})
    provider = HoodMarketDataProvider(client, paper_settings)
    with pytest.raises(HoodToolError):
        provider.get_option_chain_candidates("AAPL")


def test_option_chain_candidates_skips_chain_on_instruments_tool_error(paper_settings, now):
    client = _happy_client(
        now,
        chains=[{"id": "chain-1", "symbol": "AAPL"}],
        raise_on={"get_option_instruments"},
    )
    provider = HoodMarketDataProvider(client, paper_settings)
    assert provider.get_option_chain_candidates("AAPL") == []
