"""Tests for src/features/volume.py."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from src.data.bar import Bar
from src.features.volume import RelativeVolume, RollingVolume, VolumeChange, VolumePercentile


def _bars(volumes: list[int]):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=1, high=2, low=0.5, close=1.5, volume=v)
        for i, v in enumerate(volumes)
    ]


def test_rolling_volume_matches_manual_mean():
    volumes = [100, 200, 300, 400]
    bars = _bars(volumes)
    values = RollingVolume(2).compute(bars)
    assert values[0] is None
    assert math.isclose(values[1], 150.0)
    assert math.isclose(values[3], 350.0)


def test_volume_change_percent():
    bars = _bars([100, 150])
    values = VolumeChange(1).compute(bars)
    assert math.isclose(values[1], 0.5)


def test_relative_volume_excludes_current_bar():
    # Trailing window average of [100, 100] is 100; a spike to 400 on the
    # 3rd bar should read 4.0, since the average excludes that spike bar.
    bars = _bars([100, 100, 400])
    values = RelativeVolume(2).compute(bars)
    assert values[0] is None and values[1] is None
    assert math.isclose(values[2], 4.0)


def test_volume_percentile_between_zero_and_one():
    volumes = [1000 + (i % 7) * 50 for i in range(120)]
    bars = _bars(volumes)
    values = VolumePercentile(window=10, lookback=30).compute(bars)
    non_null = [v for v in values if v is not None]
    assert non_null
    assert all(0.0 <= v <= 1.0 for v in non_null)
