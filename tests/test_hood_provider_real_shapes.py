"""Regression tests built directly from REAL HOOD MCP responses captured
via live, read-only calls during verification of hood_provider.py:

  - get_equity_quotes(symbols=["SPY"])
  - get_equity_historicals(symbols=["SPY"], start_time=..., interval="5minute")
  - get_option_chains(underlying_symbol="SPY")
  - get_option_instruments(chain_id=<SPY chain>, expiration_dates="2026-08-21",
        type="call", strike_price="780.0000")
  - get_option_quotes(instrument_ids=[<the $780 call's instrument id>])
  - get_option_historicals(instrument_ids=[<same>], start_time=..., interval="5minute")

Bar arrays below are trimmed to a handful of entries for readability; every
field name, nesting level, and value type (strings for prices, ints for
volume/open_interest, etc.) is copied verbatim from the real payloads. If a
future Robinhood response shape changes, these are the tests that should
fail first — re-verify with the same kind of live read-only call and
update both the fixture and the parser together.

No order-placement/review/cancellation tool was used to produce any of
this data.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.market.hood_provider import (
    _parse_bars,
    _parse_equity_quote,
    _parse_option_quote,
    _unwrap_data,
)

SPY_OPTION_ID = "8c267de1-9d48-483b-af0e-cc89ffa67b43"

# --- get_equity_quotes(symbols=["SPY"]) -----------------------------------------------------

REAL_EQUITY_QUOTES_RESPONSE = {
    "data": {
        "results": [
            {
                "quote": {
                    "symbol": "SPY",
                    "last_trade_price": "777.770000",
                    "venue_last_trade_time": "2026-08-13T19:59:59.786302302Z",
                    "last_non_reg_trade_price": "778.605000",
                    "venue_last_non_reg_trade_time": "2026-08-14T11:42:12.964116389Z",
                    "adjusted_previous_close": "777.880000",
                    "previous_close": "777.880000",
                    "previous_close_date": "2026-08-13",
                    "bid_price": "778.590000",
                    "venue_bid_time": "2026-08-14T11:42:16.426377937Z",
                    "ask_price": "778.630000",
                    "venue_ask_time": "2026-08-14T11:42:16.426377937Z",
                    "has_traded": True,
                    "state": "active",
                },
                "close": {
                    "symbol": "SPY",
                    "date": "2026-08-13",
                    "price": "777.88",
                    "interpolated": False,
                    "source": "sip-list-exchange-close",
                },
            }
        ]
    },
    "guide": "Each entry in results pairs the live quote with the official prior-session close...",
}


def test_real_equity_quotes_response_parses_correctly():
    quote = _parse_equity_quote(REAL_EQUITY_QUOTES_RESPONSE, "SPY")
    # venue_last_non_reg_trade_time (2026-08-14T11:42) is more recent than
    # venue_last_trade_time (2026-08-13T19:59) in this real payload, so the
    # non-regular-session price/timestamp wins per get_equity_quotes' own
    # documented guidance.
    assert quote.symbol == "SPY"
    assert quote.last_trade_price == 778.605
    assert quote.previous_close == 777.88  # from the official close, not adjusted_previous_close
    assert quote.as_of == datetime(2026, 8, 14, 11, 42, 12, 964116, tzinfo=timezone.utc)


def test_real_equity_quotes_response_unwraps_under_data_key():
    data = _unwrap_data(REAL_EQUITY_QUOTES_RESPONSE, "get_equity_quotes")
    assert "results" in data
    assert data["results"][0]["quote"]["symbol"] == "SPY"


# --- get_equity_historicals(symbols=["SPY"], interval="5minute") ---------------------------

REAL_EQUITY_HISTORICALS_RESPONSE = {
    "data": {
        "results": [
            {
                "symbol": "SPY",
                "interval": "5minute",
                "bounds": "regular",
                "bars": [
                    {
                        "begins_at": "2026-08-13T13:30:00Z",
                        "open_price": "774.860000",
                        "close_price": "775.380800",
                        "high_price": "775.490000",
                        "low_price": "774.111000",
                        "volume": 289021,
                        "session": "reg",
                    },
                    {
                        "begins_at": "2026-08-13T13:35:00Z",
                        "open_price": "775.400000",
                        "close_price": "776.440000",
                        "high_price": "776.470000",
                        "low_price": "775.360000",
                        "volume": 354071,
                        "session": "reg",
                    },
                    {
                        "begins_at": "2026-08-13T19:55:00Z",
                        "open_price": "777.530000",
                        "close_price": "777.770000",
                        "high_price": "777.935000",
                        "low_price": "777.365000",
                        "volume": 666110,
                        "session": "reg",
                    },
                ],
            }
        ]
    },
    "guide": "Bars are left-edge labeled in UTC...",
}


def test_real_equity_historicals_response_parses_correctly():
    bars = _parse_bars(REAL_EQUITY_HISTORICALS_RESPONSE, "get_equity_historicals")
    assert len(bars) == 3
    first = bars[0]
    assert first.start_time == datetime(2026, 8, 13, 13, 30, tzinfo=timezone.utc)
    assert first.open == 774.86
    assert first.high == 775.49
    assert first.low == 774.111
    assert first.close == 775.3808
    assert first.volume == 289021
    assert first.interpolated is False


# --- get_option_chains(underlying_symbol="SPY") ---------------------------------------------

REAL_OPTION_CHAINS_RESPONSE = {
    "data": {
        "chains": [
            {
                "id": "c277b118-58d9-4060-8dc5-a3b5898955cb",
                "symbol": "SPY",
                "can_open_position": True,
                "expiration_dates": ["2026-08-14", "2026-08-17", "2026-08-21", "2026-09-18"],
                "trade_value_multiplier": "100.0000",
                "min_ticks": {"above_tick": "0.01", "below_tick": "0.01", "cutoff_price": "0.00"},
                "settle_on_open": False,
                "sellout_time_to_expiration": 1800,
            }
        ]
    },
    "guide": "Pass id to get_option_instruments as chain_id to list contracts...",
}


def test_real_option_chains_response_unwraps_correctly():
    data = _unwrap_data(REAL_OPTION_CHAINS_RESPONSE, "get_option_chains")
    chains = data["chains"]
    assert len(chains) == 1
    assert chains[0]["id"] == "c277b118-58d9-4060-8dc5-a3b5898955cb"
    assert "2026-08-21" in chains[0]["expiration_dates"]


# --- get_option_instruments(chain_id=..., expiration_dates="2026-08-21", type="call", strike_price="780.0000") ---

REAL_OPTION_INSTRUMENTS_RESPONSE = {
    "data": {
        "instruments": [
            {
                "id": SPY_OPTION_ID,
                "chain_id": "c277b118-58d9-4060-8dc5-a3b5898955cb",
                "chain_symbol": "SPY",
                "underlying_type": "equity",
                "expiration_date": "2026-08-21",
                "sellout_datetime": "2026-08-21T19:45:00+00:00",
                "strike_price": "780.0000",
                "type": "call",
                "state": "active",
                "tradability": "tradable",
                "trade_value_multiplier": "100.0000",
                "min_ticks": {"above_tick": "0.01", "below_tick": "0.01", "cutoff_price": "0.00"},
            }
        ]
    },
    "guide": "Present chain_symbol, expiration_date, type, strike_price...",
}


def test_real_option_instruments_response_unwraps_correctly():
    data = _unwrap_data(REAL_OPTION_INSTRUMENTS_RESPONSE, "get_option_instruments")
    instruments = data["instruments"]
    assert len(instruments) == 1
    assert instruments[0]["id"] == SPY_OPTION_ID
    assert instruments[0]["strike_price"] == "780.0000"
    assert instruments[0]["type"] == "call"
    assert instruments[0]["state"] == "active"
    assert instruments[0]["tradability"] == "tradable"


# --- get_option_quotes(instrument_ids=[SPY_OPTION_ID]) --------------------------------------

REAL_OPTION_QUOTES_RESPONSE = {
    "data": {
        "results": [
            {
                "quote": {
                    "instrument_id": SPY_OPTION_ID,
                    "ask_price": "3.630000",
                    "ask_size": 1,
                    "bid_price": "3.600000",
                    "bid_size": 60,
                    "break_even_price": "783.620000",
                    "adjusted_mark_price": "3.620000",
                    "mark_price": "3.615000",
                    "previous_close_price": "3.620000",
                    "previous_close_date": "2026-08-13",
                    "implied_volatility": "0.099465",
                    "delta": "0.443750",
                    "gamma": "0.035966",
                    "rho": "0.068826",
                    "theta": "-0.330405",
                    "vega": "0.436098",
                    "open_interest": 67754,
                    "volume": 26512,
                    "chance_of_profit_long": "0.314367",
                    "chance_of_profit_short": "0.685633",
                    "updated_at": "2026-08-13T20:14:59.68569685Z",
                },
                "close": {
                    "instrument_id": SPY_OPTION_ID,
                    "symbol": "SPY",
                    "date": "2026-08-13",
                    "price": "3.62",
                    "interpolated": False,
                    "source": "ddb-market-snapshot",
                },
            }
        ]
    },
    "guide": "Each entry in results pairs the live quote with the official prior-session close...",
}


def test_real_option_quotes_response_parses_correctly():
    quote = _parse_option_quote(REAL_OPTION_QUOTES_RESPONSE, SPY_OPTION_ID)
    assert quote.instrument_id == SPY_OPTION_ID
    assert quote.bid_price == 3.60
    assert quote.ask_price == 3.63
    assert quote.last_trade_price == 3.615  # mark_price, NOT a last_trade_price field (doesn't exist)
    assert quote.previous_close == 3.62
    assert quote.volume == 26512
    assert quote.open_interest == 67754
    assert quote.as_of == datetime(2026, 8, 13, 20, 14, 59, 685696, tzinfo=timezone.utc)
    assert 0 < quote.spread_pct < 0.02  # a liquid, tight-spread contract


# --- get_option_historicals(instrument_ids=[SPY_OPTION_ID], interval="5minute") -------------

REAL_OPTION_HISTORICALS_RESPONSE = {
    "data": {
        "results": [
            {
                "instrument_id": SPY_OPTION_ID,
                "occ_symbol": "SPY   260821C00780000",
                "symbol": "SPY",
                "interval": "5minute",
                "bounds": "regular",
                "bars": [
                    {
                        "begins_at": "2026-08-13T13:30:00Z",
                        "open_price": "2.690000",
                        "high_price": "2.690000",
                        "low_price": "2.690000",
                        "close_price": "2.690000",
                        "session": "reg",
                    },
                    {
                        "begins_at": "2026-08-13T13:35:00Z",
                        "open_price": "2.690000",
                        "high_price": "3.140000",
                        "low_price": "2.690000",
                        "close_price": "3.140000",
                        "session": "reg",
                    },
                    {
                        "begins_at": "2026-08-13T19:55:00Z",
                        "open_price": "3.570000",
                        "high_price": "3.570000",
                        "low_price": "3.510000",
                        "close_price": "3.550000",
                        "session": "reg",
                    },
                ],
                # Confirmed live: no "volume" key anywhere in an option bar.
            }
        ]
    },
    "guide": "Bars are left-edge labeled in UTC... Option bars carry no volume.",
}


def test_real_option_historicals_response_parses_correctly():
    bars = _parse_bars(REAL_OPTION_HISTORICALS_RESPONSE, "get_option_historicals")
    assert len(bars) == 3
    first = bars[0]
    assert first.start_time == datetime(2026, 8, 13, 13, 30, tzinfo=timezone.utc)
    assert first.open == 2.69
    assert first.high == 2.69
    assert first.low == 2.69
    assert first.close == 2.69
    assert first.volume == 0  # no volume field in a real option bar -> defaults to 0, never fabricated
    assert first.interpolated is False


def test_real_option_historicals_occ_symbol_matches_requested_contract():
    """occ_symbol is a sanity cross-check we're looking at the right
    contract: 'SPY   260821C00780000' encodes SPY, exp 2026-08-21, Call,
    strike 780.000 — matching the $780 call this fixture was captured for."""
    data = _unwrap_data(REAL_OPTION_HISTORICALS_RESPONSE, "get_option_historicals")
    occ_symbol = data["results"][0]["occ_symbol"]
    assert occ_symbol.strip().startswith("SPY")
    assert "260821C00780000" in occ_symbol
