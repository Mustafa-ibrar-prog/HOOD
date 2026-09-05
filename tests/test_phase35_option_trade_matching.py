"""Phase 35, Part C/D — matching real underlying signals to real option
contract observations."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.options.phase35_option_trade_matching import find_matching_contract_trade, match_all_signals
from src.options.phase35_underlying_signal import UnderlyingSignalEvent


def _row(option_id, d, *, underlying="AAPL", call_put="call", dte=20, strike=100.0, bid=1.4, ask=1.6):
    return {
        "underlying_symbol": underlying, "call_put": call_put, "dte": dte, "strike": strike,
        "bid": bid, "ask": ask, "volume": 50, "open_interest": 200,
        "timestamp": datetime(d.year, d.month, d.day, tzinfo=timezone.utc), "option_id": option_id,
        "expiration": date(d.year, d.month, d.day),
    }


def test_finds_the_real_nearest_strike_within_dte_window():
    signal = UnderlyingSignalEvent("AAPL", date(2020, 1, 10), underlying_price=101.0, signals_fired=())
    rows = [
        _row("OPT_FAR", date(2020, 1, 10), strike=150.0),
        _row("OPT_NEAR", date(2020, 1, 10), strike=100.0),
    ]
    m = find_matching_contract_trade(signal, rows)
    assert m is not None
    assert m.option_id == "OPT_NEAR"


def test_rejects_a_contract_outside_the_dte_window():
    signal = UnderlyingSignalEvent("AAPL", date(2020, 1, 10), underlying_price=100.0, signals_fired=())
    rows = [_row("OPT1", date(2020, 1, 10), dte=200)]  # outside [7, 45]
    m = find_matching_contract_trade(signal, rows)
    assert m is None


def test_rejects_a_put_option():
    signal = UnderlyingSignalEvent("AAPL", date(2020, 1, 10), underlying_price=100.0, signals_fired=())
    rows = [_row("OPT1", date(2020, 1, 10), call_put="put")]
    m = find_matching_contract_trade(signal, rows)
    assert m is None


def test_rejects_a_different_underlying():
    signal = UnderlyingSignalEvent("AAPL", date(2020, 1, 10), underlying_price=100.0, signals_fired=())
    rows = [_row("OPT1", date(2020, 1, 10), underlying="GOOG")]
    m = find_matching_contract_trade(signal, rows)
    assert m is None


def test_no_match_beyond_date_tolerance():
    signal = UnderlyingSignalEvent("AAPL", date(2020, 1, 10), underlying_price=100.0, signals_fired=())
    rows = [_row("OPT1", date(2020, 3, 1))]  # far outside the default 5-day tolerance
    m = find_matching_contract_trade(signal, rows, date_tolerance_days=5)
    assert m is None


def test_management_rows_are_the_same_contracts_own_later_real_observations():
    signal = UnderlyingSignalEvent("AAPL", date(2020, 1, 10), underlying_price=100.0, signals_fired=())
    rows = [
        _row("OPT1", date(2020, 1, 10)),
        _row("OPT1", date(2020, 1, 15)),
        _row("OPT2", date(2020, 1, 12)),  # a different contract -- must not leak into OPT1's management rows
    ]
    m = find_matching_contract_trade(signal, rows)
    assert m is not None
    assert m.option_id == "OPT1"
    assert len(m.management_rows) == 1
    assert m.management_rows[0]["timestamp"].date() == date(2020, 1, 15)


def test_match_all_signals_accounts_for_every_signal_matched_or_unmatched():
    signals = (
        UnderlyingSignalEvent("AAPL", date(2020, 1, 10), underlying_price=100.0, signals_fired=()),
        UnderlyingSignalEvent("AAPL", date(2020, 6, 1), underlying_price=100.0, signals_fired=()),  # no nearby contract
    )
    rows = [_row("OPT1", date(2020, 1, 10))]
    matched, unmatched = match_all_signals(signals, rows)
    assert len(matched) == 1
    assert len(unmatched) == 1
    assert unmatched[0].signal_date == date(2020, 6, 1)
