"""Tests for Bar/Quote normalization, timezone enforcement, and the
adapters from the existing live-path market models (PriceBar/EquityQuote/
OptionQuote)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.data.bar import Bar, Quote
from src.market.models import EquityQuote, OptionQuote, PriceBar


def _ts(*args, **kwargs) -> datetime:
    return datetime(*args, tzinfo=timezone.utc, **kwargs)


def test_bar_requires_timezone_aware_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        Bar(timestamp=datetime(2026, 1, 1), symbol="AAPL", timeframe="day", open=1, high=2, low=1, close=1.5, volume=100)


def test_bar_rejects_non_utc_offset():
    from datetime import timedelta, timezone as tz

    non_utc = datetime(2026, 1, 1, tzinfo=tz(timedelta(hours=5)))
    with pytest.raises(ValueError, match="UTC"):
        Bar(timestamp=non_utc, symbol="AAPL", timeframe="day", open=1, high=2, low=1, close=1.5, volume=100)


def test_bar_rejects_high_below_low():
    with pytest.raises(ValueError, match="high must be >= "):
        Bar(timestamp=_ts(2026, 1, 1), symbol="AAPL", timeframe="day", open=1, high=1, low=2, close=1.5, volume=100)


def test_bar_rejects_negative_volume():
    with pytest.raises(ValueError, match="volume must be >= 0"):
        Bar(timestamp=_ts(2026, 1, 1), symbol="AAPL", timeframe="day", open=1, high=2, low=1, close=1.5, volume=-1)


def test_bar_round_trips_through_dict():
    bar = Bar(timestamp=_ts(2026, 1, 1, 9, 30), symbol="AAPL", timeframe="5minute", open=1.1, high=1.3, low=1.0, close=1.2, volume=500)
    restored = Bar.from_dict(bar.to_dict())
    assert restored == bar


def test_bar_from_dict_coerces_naive_timestamp_to_utc():
    data = {
        "timestamp": "2026-01-01T09:30:00",  # no tzinfo in the string
        "symbol": "AAPL",
        "timeframe": "5minute",
        "open": 1.0,
        "high": 1.1,
        "low": 0.9,
        "close": 1.05,
        "volume": 10,
    }
    bar = Bar.from_dict(data)
    assert bar.timestamp.tzinfo is not None
    assert bar.timestamp.utcoffset().total_seconds() == 0


def test_bar_from_price_bar_adapter():
    price_bar = PriceBar(start_time=_ts(2026, 8, 17, 13, 30), open=2.31, high=2.33, low=2.24, close=2.25, volume=1671229)
    bar = Bar.from_price_bar(price_bar, symbol="plug", timeframe="5minute")
    assert bar.symbol == "PLUG"  # normalized to uppercase
    assert bar.timeframe == "5minute"
    assert bar.open == price_bar.open
    assert bar.close == price_bar.close
    assert bar.volume == price_bar.volume
    assert bar.source == "hood"


def test_bar_from_price_bar_handles_naive_start_time():
    price_bar = PriceBar(start_time=datetime(2026, 8, 17, 13, 30), open=1, high=2, low=1, close=1.5, volume=10)
    bar = Bar.from_price_bar(price_bar, symbol="AAPL", timeframe="day")
    assert bar.timestamp.tzinfo is not None


def test_quote_from_option_quote_populates_bid_ask_and_mark_as_trade_price():
    oq = OptionQuote(
        instrument_id="abc",
        bid_price=1.03,
        ask_price=1.07,
        last_trade_price=1.05,
        previous_close=0.90,
        volume=500,
        open_interest=1000,
        as_of=_ts(2026, 8, 17, 14, 0),
    )
    quote = Quote.from_option_quote(oq, symbol="aapl")
    assert quote.symbol == "AAPL"
    assert quote.bid == 1.03
    assert quote.ask == 1.07
    assert quote.trade_price == 1.05  # documented as the mark price, not a true last trade
    assert quote.bid_size is None
    assert quote.ask_size is None
    assert quote.trade_size is None


def test_quote_from_equity_quote_never_invents_bid_ask():
    eq = EquityQuote(symbol="AAPL", last_trade_price=231.0, previous_close=228.0, as_of=_ts(2026, 8, 17, 14, 0))
    quote = Quote.from_equity_quote(eq)
    assert quote.trade_price == 231.0
    # The existing EquityQuote model does not capture bid/ask today — see
    # module docstring. This must stay None, never fabricated.
    assert quote.bid is None
    assert quote.ask is None


def test_quote_requires_timezone_aware_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        Quote(timestamp=datetime(2026, 1, 1), symbol="AAPL")
