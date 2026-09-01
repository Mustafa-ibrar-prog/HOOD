"""Tests for src/features/momentum.py."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from src.data.bar import Bar
from src.features.momentum import Momentum, MovingAverage, MovingAverageDistance, RateOfChange


def _bars(closes: list[float]):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=c, high=c + 1, low=c - 1, close=c, volume=100)
        for i, c in enumerate(closes)
    ]


def test_momentum_raw_difference():
    bars = _bars([100.0, 102.0, 105.0])
    values = Momentum(2).compute(bars)
    assert values[0] is None and values[1] is None
    assert math.isclose(values[2], 5.0)


def test_rate_of_change_percent():
    bars = _bars([100.0, 110.0])
    values = RateOfChange(1).compute(bars)
    assert math.isclose(values[1], 10.0)


def test_moving_average_matches_manual_mean():
    closes = [10.0, 20.0, 30.0, 40.0]
    bars = _bars(closes)
    values = MovingAverage(3).compute(bars)
    assert values[0] is None and values[1] is None
    assert math.isclose(values[2], (10 + 20 + 30) / 3)
    assert math.isclose(values[3], (20 + 30 + 40) / 3)


def test_moving_average_lookback():
    assert MovingAverage(20).spec.lookback == 19


def test_moving_average_distance_sign():
    # A rising series: current close should sit above its trailing MA.
    closes = [100.0, 101.0, 102.0, 110.0]
    bars = _bars(closes)
    values = MovingAverageDistance(3).compute(bars)
    assert values[3] > 0


def test_moving_average_distance_none_before_enough_history():
    bars = _bars([100.0, 101.0])
    values = MovingAverageDistance(5).compute(bars)
    assert all(v is None for v in values)
