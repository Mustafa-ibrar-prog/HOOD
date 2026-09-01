"""Tests for src/features/price.py."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from src.features.price import CumulativeReturn, LogReturn, RollingReturn, SimpleReturn


def _bars(closes: list[float]):
    from src.data.bar import Bar

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=c, high=c + 1, low=c - 1, close=c, volume=100)
        for i, c in enumerate(closes)
    ]


def test_simple_return_first_period_values_are_none():
    bars = _bars([100.0, 110.0, 121.0])
    values = SimpleReturn(1).compute(bars)
    assert values[0] is None
    assert values[1] == 0.10
    assert values[2] == 0.10


def test_simple_return_lookback_matches_period():
    assert SimpleReturn(3).spec.lookback == 3


def test_log_return_matches_math_log():
    bars = _bars([100.0, 110.0])
    values = LogReturn(1).compute(bars)
    assert values[0] is None
    assert math.isclose(values[1], math.log(1.1))


def test_cumulative_return_is_zero_at_first_bar_and_defined_immediately():
    bars = _bars([100.0, 110.0, 121.0])
    values = CumulativeReturn().compute(bars)
    assert values[0] == 0.0  # no None — cumulative return needs no prior history
    assert math.isclose(values[1], 0.10)
    assert math.isclose(values[2], 0.21)


def test_rolling_return_over_window():
    bars = _bars([100.0, 105.0, 110.0, 120.0])
    values = RollingReturn(2).compute(bars)
    assert values[0] is None
    assert values[1] is None
    assert math.isclose(values[2], (110.0 - 100.0) / 100.0)
    assert math.isclose(values[3], (120.0 - 105.0) / 105.0)


def test_simple_return_rejects_non_positive_period():
    import pytest

    with pytest.raises(ValueError):
        SimpleReturn(0)
