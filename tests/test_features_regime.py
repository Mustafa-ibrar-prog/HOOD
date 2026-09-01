"""Tests for src/features/regime.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.data.bar import Bar
from src.features.regime import MomentumRegime, TrendRegime, VolatilityRegime


def _bars(closes: list[float]):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=c, high=c + 1, low=c - 1, close=c, volume=100)
        for i, c in enumerate(closes)
    ]


def test_trend_regime_uptrend_is_positive_one():
    closes = [100.0 + i for i in range(60)]  # steadily rising
    bars = _bars(closes)
    values = TrendRegime(fast_window=5, slow_window=20).compute(bars)
    assert values[-1] == 1.0


def test_trend_regime_downtrend_is_negative_one():
    closes = [200.0 - i for i in range(60)]  # steadily falling
    bars = _bars(closes)
    values = TrendRegime(fast_window=5, slow_window=20).compute(bars)
    assert values[-1] == -1.0


def test_trend_regime_none_before_slow_window_ready():
    bars = _bars([100.0] * 10)
    values = TrendRegime(fast_window=5, slow_window=20).compute(bars)
    assert all(v is None for v in values)


def test_volatility_regime_buckets_are_within_range():
    closes = [100.0 + (i % 5) * (1 if i % 2 == 0 else -1) for i in range(150)]
    bars = _bars(closes)
    values = VolatilityRegime(window=10, lookback=30, n_buckets=5).compute(bars)
    non_null = [v for v in values if v is not None]
    assert non_null
    assert all(v in (0.0, 1.0, 2.0, 3.0, 4.0) for v in non_null)


def test_momentum_regime_positive_on_rising_series():
    closes = [100.0 + i for i in range(20)]
    bars = _bars(closes)
    values = MomentumRegime(period=5).compute(bars)
    assert values[-1] == 1.0
