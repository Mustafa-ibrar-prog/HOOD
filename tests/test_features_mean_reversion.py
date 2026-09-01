"""Tests for src/features/mean_reversion.py."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from src.data.bar import Bar
from src.features.mean_reversion import DistanceFromMA, RollingZScore, StandardizedReturns
from src.features.momentum import MovingAverageDistance


def _bars(closes: list[float]):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=c, high=c + 1, low=c - 1, close=c, volume=100)
        for i, c in enumerate(closes)
    ]


def test_zscore_of_constant_series_is_none_not_a_fabricated_zero():
    # A constant series has zero stdev, making the z-score formula a 0/0
    # division — genuinely undefined, not "no deviation". Consistent with
    # this codebase's "never fabricate, return None on undefined" ethos
    # (see e.g. OptionQuote.spread_pct returning inf rather than guessing).
    bars = _bars([100.0] * 10)
    values = RollingZScore(5).compute(bars)
    assert values[4] is None


def test_zscore_extreme_value_is_positive_and_large():
    closes = [100.0] * 9 + [200.0]
    bars = _bars(closes)
    values = RollingZScore(10).compute(bars)
    assert values[9] > 2.0


def test_distance_from_ma_has_distinct_feature_name_from_momentum_variant():
    dist = DistanceFromMA(20)
    ma_dist = MovingAverageDistance(20)
    assert dist.spec.name != ma_dist.spec.name
    assert dist.spec.name == "distance_from_ma_20"


def test_distance_from_ma_same_arithmetic_as_momentum_variant():
    bars = _bars([100.0, 102.0, 105.0, 110.0, 108.0])
    a = DistanceFromMA(3).compute(bars)
    b = MovingAverageDistance(3).compute(bars)
    assert a == b


def test_standardized_returns_none_until_enough_history():
    bars = _bars([100.0, 101.0, 102.0])
    values = StandardizedReturns(window=10, return_period=1).compute(bars)
    assert all(v is None for v in values)
