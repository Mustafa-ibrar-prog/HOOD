"""Tests for the data-quality engine: every documented check, plus the
"never silently fix, only flag" guarantee and the report's status
rollup."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.data.bar import Bar
from src.data.quality import validate_bars


def _bar(minutes: int, **overrides) -> Bar:
    defaults = dict(
        timestamp=datetime(2026, 1, 1, 9, 30, tzinfo=timezone.utc) + timedelta(minutes=minutes),
        symbol="AAPL",
        timeframe="5minute",
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1000,
    )
    defaults.update(overrides)
    return Bar(**defaults)


def test_clean_series_is_status_ok():
    bars = [_bar(5 * i) for i in range(10)]
    report = validate_bars(bars)
    assert report.status == "OK"
    assert report.issues == ()


def test_negative_price_is_flagged():
    bars = [_bar(0, open=-1.0)]
    report = validate_bars(bars)
    assert report.status == "ERROR"
    assert "NEGATIVE_PRICE" in report.counts_by_code


def test_zero_price_is_flagged_as_invalid():
    bars = [_bar(0, close=0.0)]
    report = validate_bars(bars)
    assert report.counts_by_code.get("INVALID_PRICE") == 1


def test_negative_volume_is_rejected_at_construction_by_bar_itself():
    # Bar.__post_init__ already refuses volume < 0 (see test_data_bar.py),
    # so a negative-volume Bar can never actually reach validate_bars() —
    # the INVALID_VOLUME check below is defense-in-depth for a future,
    # less-guarded ingestion path, not something exercisable through Bar's
    # own constructor today.
    import pytest

    with pytest.raises(ValueError, match="volume must be >= 0"):
        _bar(0, volume=-5)


def test_invalid_ohlc_high_below_close_is_flagged():
    # Bar's own __post_init__ only rejects high < low, so a high that's
    # below open/close (but not below low) can still be constructed — the
    # quality engine is what must catch that.
    bars = [_bar(0, open=100.0, high=100.2, low=99.0, close=105.0)]  # close > high
    report = validate_bars(bars)
    assert report.counts_by_code.get("INVALID_OHLC") == 1


def test_valid_ohlc_boundary_is_not_flagged():
    bars = [_bar(0, open=100.0, high=101.0, low=99.0, close=101.0)]  # close == high, fine
    report = validate_bars(bars)
    assert "INVALID_OHLC" not in report.counts_by_code


def test_duplicate_timestamps_are_flagged():
    ts = datetime(2026, 1, 1, 9, 30, tzinfo=timezone.utc)
    bars = [
        Bar(timestamp=ts, symbol="AAPL", timeframe="5minute", open=1, high=2, low=1, close=1.5, volume=10),
        Bar(timestamp=ts, symbol="AAPL", timeframe="5minute", open=1, high=2, low=1, close=1.6, volume=11),
    ]
    report = validate_bars(bars)
    assert report.counts_by_code.get("DUPLICATE_TIMESTAMP") == 1


def test_duplicate_full_rows_are_flagged():
    b = _bar(0)
    b2 = Bar(**{**b.to_dict(), "timestamp": b.timestamp})  # identical row, different object
    report = validate_bars([b, b2])
    assert report.counts_by_code.get("DUPLICATE_RECORD") == 1
    # Two fully-identical rows necessarily also share a timestamp, so
    # DUPLICATE_TIMESTAMP (ERROR) fires alongside DUPLICATE_RECORD
    # (WARNING) — overall status is ERROR, driven by the timestamp check.
    assert report.counts_by_code.get("DUPLICATE_TIMESTAMP") == 1
    assert report.status == "ERROR"


def test_warning_only_issue_rolls_up_to_warning_not_error():
    # A missing-interval gap is WARNING severity and no ERROR-level issue
    # is present here — overall status must roll up to WARNING, not ERROR.
    bars = [_bar(0), _bar(5), _bar(25)]  # a gap of ~4 missing 5-minute bars
    report = validate_bars(bars)
    assert report.counts_by_code.get("MISSING_INTERVAL") == 1
    assert report.status == "WARNING"


def test_out_of_order_records_are_flagged():
    bars = [_bar(10), _bar(0)]  # descending
    report = validate_bars(bars)
    assert report.counts_by_code.get("OUT_OF_ORDER") == 1


def test_missing_intervals_are_flagged():
    bars = [_bar(0), _bar(5), _bar(25)]  # a gap of 4 missing 5-minute bars
    report = validate_bars(bars)
    assert report.counts_by_code.get("MISSING_INTERVAL") == 1


def test_large_gap_is_suspicious_not_missing_interval():
    bars = [_bar(0), _bar(0 + 10 * 60)]  # 10 hour gap
    report = validate_bars(bars)
    assert report.counts_by_code.get("SUSPICIOUS_GAP") == 1
    assert "MISSING_INTERVAL" not in report.counts_by_code


def test_stale_data_is_flagged_when_now_is_far_past_last_bar():
    bars = [_bar(0)]
    now = bars[0].timestamp + timedelta(hours=5)
    report = validate_bars(bars, stale_after_seconds=3600, now=now)
    assert report.counts_by_code.get("STALE_DATA") == 1


def test_stale_data_not_flagged_when_recent():
    bars = [_bar(0)]
    now = bars[0].timestamp + timedelta(seconds=30)
    report = validate_bars(bars, stale_after_seconds=3600, now=now)
    assert "STALE_DATA" not in report.counts_by_code


def test_empty_series_is_ok_with_zero_records():
    report = validate_bars([])
    assert report.record_count == 0
    assert report.status == "OK"


def test_render_matches_documented_format():
    bars = [_bar(0)]
    text = validate_bars(bars).render()
    assert "Dataset:" in text
    assert "Records:" in text
    assert "Status:" in text
    assert "OK" in text


def test_never_mutates_input_bars():
    bars = [_bar(0, open=-1.0)]
    original = list(bars)
    validate_bars(bars)
    assert bars == original  # only flags, never "fixes"
