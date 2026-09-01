"""Tests for src/features/volatility.py."""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone

from src.data.bar import Bar
from src.features.volatility import ATR, RealizedVolatility, RollingStd, VolatilityPercentile


def _bars(closes: list[float], highs=None, lows=None):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    highs = highs or [c + 1 for c in closes]
    lows = lows or [c - 1 for c in closes]
    return [
        Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=c, high=h, low=l, close=c, volume=100)
        for i, (c, h, l) in enumerate(zip(closes, highs, lows))
    ]


def test_rolling_std_matches_stdlib_sample_stdev():
    closes = [10.0, 12.0, 9.0, 15.0, 11.0]
    bars = _bars(closes)
    values = RollingStd(4).compute(bars)
    assert values[2] is None
    expected = statistics.stdev(closes[0:4])
    assert math.isclose(values[3], expected)


def test_realized_volatility_is_none_until_window_and_log_returns_available():
    bars = _bars([100.0] * 25)  # flat price -> zero vol once computed
    values = RealizedVolatility(20).compute(bars)
    assert values[19] is None  # lookback == window == 20, first valid at index 20
    assert values[20] is not None
    assert math.isclose(values[20], 0.0, abs_tol=1e-9)


def test_atr_uses_high_low_close():
    closes = [100.0, 101.0, 99.0, 103.0]
    highs = [101.0, 102.5, 100.0, 105.0]
    lows = [99.0, 100.0, 97.0, 101.0]
    bars = _bars(closes, highs=highs, lows=lows)
    values = ATR(2).compute(bars)
    assert values[0] is None
    assert values[1] is not None
    assert values[1] > 0


def test_volatility_percentile_is_between_zero_and_one():
    closes = [100.0 + (i % 5) * (1 if i % 2 == 0 else -1) for i in range(150)]
    bars = _bars(closes)
    values = VolatilityPercentile(window=10, lookback=30).compute(bars)
    non_null = [v for v in values if v is not None]
    assert non_null  # some values should be computable
    assert all(0.0 <= v <= 1.0 for v in non_null)


def test_atr_rejects_bad_window():
    import pytest

    with pytest.raises(ValueError):
        ATR(0)
