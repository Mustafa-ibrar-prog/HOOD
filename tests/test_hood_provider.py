"""Tests for HoodMarketDataProvider, using a fake HoodToolClient built from
mocked responses shaped like the real HOOD MCP tools. No real network call,
no real MCP tool call, and — critically — no order-placement method exists
anywhere on the fake client or the Protocol it implements.
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


def _bar(minutes_ago: int, close: float, volume: int = 1000, interpolated: bool = False, now=None):
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(minutes=minutes_ago)
    return {
        "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "open": close - 0.05,
        "high": close + 0.05,
        "low": close - 0.10,
        "close": close,
        "volume": volume,
        "interpolated": interpolated,
    }


class FakeHoodToolClient:
    """Implements HoodToolClient with entirely canned, mocked responses.
    Never touches a network, an MCP tool, or an order-placement endpoint —
    there is no such method to call."""

    def __init__(
        self,
        *,
        equity_quotes=None,
        option_quotes=None,
        equity_bars=None,
        option_bars=None,
        chains=None,
        instruments=None,
        raise_on=None,
    ):
        self.equity_quotes = equity_quotes
        self.option_quotes = option_quotes
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
        return {"quotes": self.equity_quotes, "closes_error": None}

    def get_option_quotes(self, instrument_ids):
        self._maybe_raise("get_option_quotes")
        return {"quotes": self.option_quotes, "closes_error": None}

    def get_equity_historicals(self, symbols, start_time, end_time=None, interval=None, bounds=None, adjustment_type=None):
        self._maybe_raise("get_equity_historicals")
        return {"bars": self.equity_bars}

    def get_option_historicals(self, instrument_ids, start_time, end_time=None, interval=None, bounds=None):
        self._maybe_raise("get_option_historicals")
        return {"bars": self.option_bars}

    def get_option_chains(self, underlying_symbol=None, ids=None):
        self._maybe_raise("get_option_chains")
        return {"chains": self.chains}

    def get_option_instruments(self, chain_symbol=None, chain_id=None, ids=None, expiration_dates=None, strike_price=None, type=None, state=None, tradability=None, cursor=None):
        self._maybe_raise("get_option_instruments")
        return {"instruments": self.instruments}


def _happy_client(now: datetime, **overrides) -> FakeHoodToolClient:
    closes = [228.0, 229.0, 229.5, 230.2, 230.8, 231.0]
    bars = [_bar(minutes_ago=(len(closes) - i) * 5, close=c, now=now) for i, c in enumerate(closes)]
    defaults = dict(
        equity_quotes=[{"symbol": "AAPL", "last_trade_price": "231.00", "previous_close": "228.00"}],
        option_quotes=[
            {
                "instrument_id": OPTION_ID,
                "bid_price": "1.03",
                "ask_price": "1.07",
                "last_trade_price": "1.05",
                "previous_close": "0.90",
                "volume": 500,
                "open_interest": 1000,
            }
        ],
        equity_bars=bars,
        option_bars=bars,
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
    assert snapshot.option.volume == 500
    assert snapshot.option.open_interest == 1000
    assert len(snapshot.underlying_bars) == 6
    assert len(snapshot.option_bars) == 6
    # Computed locally from real fetched closes, not fabricated:
    assert snapshot.ema_fast is not None
    assert snapshot.ema_slow is not None
    assert snapshot.rsi is not None
    assert snapshot.vwap is not None
    assert snapshot.volume_ratio is not None
    assert snapshot.fetched_at == now


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
    client = _happy_client(now, equity_quotes=[])
    provider = HoodMarketDataProvider(client, paper_settings)
    with pytest.raises(QuoteUnavailableError):
        provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)


def test_missing_option_quote_raises_contract_not_found(paper_settings, now):
    client = _happy_client(now, option_quotes=[])
    provider = HoodMarketDataProvider(client, paper_settings)
    with pytest.raises(OptionContractNotFoundError):
        provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)


def test_negative_price_quote_raises_invalid_quote(paper_settings, now):
    client = _happy_client(
        now,
        option_quotes=[
            {
                "instrument_id": OPTION_ID,
                "bid_price": "-1.00",
                "ask_price": "1.07",
                "last_trade_price": "1.05",
                "previous_close": "0.90",
                "volume": 500,
                "open_interest": 1000,
            }
        ],
    )
    provider = HoodMarketDataProvider(client, paper_settings)
    with pytest.raises(InvalidQuoteError):
        provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)


def test_wide_spread_quote_is_still_returned_not_rejected(paper_settings, now):
    """The provider's job is to report reality, not to enforce risk
    policy — spread gating stays in RiskManager, unchanged."""
    client = _happy_client(
        now,
        option_quotes=[
            {
                "instrument_id": OPTION_ID,
                "bid_price": "0.50",
                "ask_price": "1.50",  # 100% spread
                "last_trade_price": "1.00",
                "previous_close": "0.90",
                "volume": 500,
                "open_interest": 1000,
            }
        ],
    )
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
    for exc_cls, client in [
        (QuoteUnavailableError, _happy_client(now, equity_quotes=[])),
        (OptionContractNotFoundError, _happy_client(now, option_quotes=[])),
        (HoodToolError, _happy_client(now, raise_on={"get_equity_quotes"})),
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
    client = _happy_client(now, equity_bars="not-a-list-of-bars")
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
        {**_bar(minutes_ago=5, close=229.0, now=now), "close": None},  # unusable row
    ]
    client = _happy_client(now, equity_bars=bars)
    provider = HoodMarketDataProvider(client, paper_settings)
    snapshot = provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)
    assert len(snapshot.underlying_bars) == 1


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


def test_missing_previous_close_is_none_not_fabricated(paper_settings, now):
    client = _happy_client(
        now,
        equity_quotes=[{"symbol": "AAPL", "last_trade_price": "231.00", "previous_close": None}],
    )
    provider = HoodMarketDataProvider(client, paper_settings)
    snapshot = provider.get_market_snapshot(OPTION_ID, UNDERLYING, now=now)
    assert snapshot.underlying.previous_close is None


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
