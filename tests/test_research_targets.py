"""Tests for src/research/targets.py: the one deliberately forward-looking
function in the whole codebase, and its guarantee that a target is None
(not fabricated) wherever the required future bar doesn't exist yet."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from src.data.bar import Bar
from src.research.targets import future_return


def _bars(closes: list[float]):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=c, high=c + 1, low=c - 1, close=c, volume=100)
        for i, c in enumerate(closes)
    ]


def test_future_return_basic_arithmetic():
    bars = _bars([100.0, 110.0, 121.0])
    values = future_return(bars, horizon=1)
    assert math.isclose(values[0], 0.10)
    assert math.isclose(values[1], 0.10)
    assert values[2] is None  # no bar at index 3 to compare against


def test_future_return_horizon_beyond_series_is_none_for_every_row():
    bars = _bars([100.0, 101.0])
    values = future_return(bars, horizon=5)
    assert values == [None, None]


def test_future_return_log_variant():
    bars = _bars([100.0, 110.0])
    values = future_return(bars, horizon=1, log=True)
    assert math.isclose(values[0], math.log(1.1))


def test_future_return_rejects_non_positive_horizon():
    with pytest.raises(ValueError):
        future_return(_bars([100.0, 101.0]), horizon=0)


def test_future_return_none_on_non_positive_price():
    bars = _bars([0.0, 100.0])
    values = future_return(bars, horizon=1)
    assert values[0] is None
