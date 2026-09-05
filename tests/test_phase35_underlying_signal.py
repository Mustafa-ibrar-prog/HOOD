"""Phase 35, Part C/D — causal underlying signal detection."""

from __future__ import annotations

from datetime import date, timedelta

from src.options.phase35_underlying_signal import compute_momentum_evidence_at, detect_entry_signal_dates


def _uptrend_series(n=60, start=date(2020, 1, 1)):
    series = []
    d = start
    price = 100.0
    for _ in range(n):
        price *= 1.01
        series.append((d, price))
        d += timedelta(days=1)
    return series


def _flat_series(n=60, start=date(2020, 1, 1)):
    series = []
    d = start
    for _ in range(n):
        series.append((d, 100.0))
        d += timedelta(days=1)
    return series


def test_detects_real_signals_on_a_clean_uptrend():
    series = _uptrend_series()
    events = detect_entry_signal_dates("TEST", series)
    assert len(events) > 0
    for e in events:
        assert e.underlying_symbol == "TEST"
        assert "breakout_continuation" in e.signals_fired


def test_no_signals_on_a_flat_series():
    series = _flat_series()
    events = detect_entry_signal_dates("TEST", series)
    assert len(events) == 0


def test_no_signal_before_minimum_causal_history_exists():
    series = _uptrend_series(n=15)  # fewer than the 22-bar minimum for breakout_continuation
    events = detect_entry_signal_dates("TEST", series)
    assert len(events) == 0


def test_signal_dates_are_real_dates_from_the_input_series():
    series = _uptrend_series()
    events = detect_entry_signal_dates("TEST", series)
    real_dates = {d for d, _ in series}
    for e in events:
        assert e.signal_date in real_dates


def test_compute_momentum_evidence_at_matches_detect_entry_signal_dates():
    """Both code paths must agree -- same underlying question, asked two
    different ways (single-date lookup vs. full forward pass)."""
    series = _uptrend_series()
    events = detect_entry_signal_dates("TEST", series)
    assert events
    evidence = compute_momentum_evidence_at(series, events[0].signal_date)
    assert evidence is not None
    assert evidence.breakout_continuation is True


def test_compute_momentum_evidence_at_returns_none_for_unknown_date():
    series = _uptrend_series()
    assert compute_momentum_evidence_at(series, date(2099, 1, 1)) is None


def test_volume_ratio_always_none_data_limited():
    """The real underlying series carries no real daily volume -- never
    fabricated."""
    series = _uptrend_series()
    events = detect_entry_signal_dates("TEST", series)
    assert events
    evidence = compute_momentum_evidence_at(series, events[0].signal_date)
    assert evidence.volume_ratio is None
