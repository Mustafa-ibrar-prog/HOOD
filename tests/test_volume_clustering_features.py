"""Phase 9, Part 4 & 21: volume-clustering feature tests — no-lookahead
(mirrors tests/test_feature_no_lookahead.py's exact methodology, run
independently against every feature in src/features/volume_clustering.py
rather than modifying that established Phase 2 test file), plus targeted
correctness checks for each feature's own semantics.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.bar import Bar
from src.features.volume_clustering import (
    ConsecutiveAbnormalVolumeStreak,
    LogRelativeVolume,
    RollingFractionAboveThreshold,
    RollingMeanRelativeVolume,
    RollingStdRelativeVolume,
    VolumeAcceleration,
    VolumeZScore,
)

CUTOFF = 100
TOTAL = 160


def _base_bars() -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    price = 100.0
    for i in range(TOTAL):
        price += (0.7 if i % 3 else -1.3)
        volume = 1000 + (i * 37) % 500 + (3000 if i % 17 == 0 else 0)  # occasional spikes, same spirit as clustering features need to detect
        bars.append(Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=price - 0.2, high=price + 0.6, low=price - 0.8, close=price, volume=volume))
    return bars


def _mutated_future(bars: list[Bar]) -> list[Bar]:
    out = list(bars[: CUTOFF + 1])
    start = bars[CUTOFF].timestamp
    for i in range(CUTOFF + 1, TOTAL):
        out.append(Bar(timestamp=start + timedelta(days=i - CUTOFF), symbol="AAPL", timeframe="day", open=1_000_000_000.0, high=2_000_000_000.0, low=500_000_000.0, close=1_500_000_000.0, volume=999_999_999))
    return out


FEATURES = [
    LogRelativeVolume(10),
    VolumeZScore(20),
    VolumeAcceleration(10),
    RollingFractionAboveThreshold(base_window=10, threshold=1.5, lookback=10),
    ConsecutiveAbnormalVolumeStreak(base_window=10, threshold=1.5),
    RollingMeanRelativeVolume(base_window=10, lookback=10),
    RollingStdRelativeVolume(base_window=10, lookback=10),
]


@pytest.mark.parametrize("feature", FEATURES, ids=lambda f: f.spec.name)
def test_feature_does_not_leak_future_data(feature):
    base = _base_bars()
    mutated = _mutated_future(base)
    values_base = feature.compute(base)
    values_mutated = feature.compute(mutated)
    for i in range(CUTOFF + 1):
        assert values_base[i] == values_mutated[i], f"{feature.spec.name} leaked future data at index {i}"


# --- targeted correctness -------------------------------------------------------------------


def _spike_bars(volumes: list[int]) -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=100, high=101, low=99, close=100 + i * 0.01, volume=v) for i, v in enumerate(volumes)]


def test_streak_resets_when_volume_returns_to_normal():
    bars = _spike_bars([1000] * 15 + [5000, 5500, 6000] + [1000] * 10)
    feature = ConsecutiveAbnormalVolumeStreak(base_window=10, threshold=1.5)
    values = feature.compute(bars)
    spike_region = values[15:18]
    assert spike_region == [1.0, 2.0, 3.0]
    assert values[19] == 0.0  # back to normal volume -> streak resets


def test_fraction_above_threshold_is_bounded_0_to_1():
    bars = _spike_bars([1000] * 15 + [5000] * 5 + [1000] * 10)
    feature = RollingFractionAboveThreshold(base_window=10, threshold=1.5, lookback=5)
    values = [v for v in feature.compute(bars) if v is not None]
    assert all(0.0 <= v <= 1.0 for v in values)
    assert max(values) > 0  # the spike region should register SOME abnormal fraction


def test_fraction_above_threshold_all_abnormal_gives_one():
    """RelativeVolume's own trailing baseline EVENTUALLY absorbs a
    sustained new volume level (once the whole baseline window is full of
    the new level, current/baseline converges back to ~1.0 — a real,
    documented property of ratio-based relative-volume features, not a
    bug in this feature). So the fraction=1.0 window is the TRANSITION
    right after the shock begins, not the tail of a long-sustained one."""
    bars = _spike_bars([1000] * 15 + [8000] * 10)
    feature = RollingFractionAboveThreshold(base_window=10, threshold=1.5, lookback=3)
    values = feature.compute(bars)
    assert max(v for v in values if v is not None) == 1.0
    assert values[-1] < 1.0  # by the end, the baseline has caught up to the new level and the ratio has normalized


def test_volume_zscore_none_on_degenerate_zero_variance_baseline():
    bars = _spike_bars([1000] * 25)  # perfectly flat volume -> zero baseline variance
    feature = VolumeZScore(window=10)
    values = feature.compute(bars)
    assert all(v is None for v in values[10:])


def test_volume_acceleration_zero_for_flat_relative_volume():
    bars = _spike_bars([1000] * 25)
    feature = VolumeAcceleration(window=10)
    values = feature.compute(bars)
    non_none = [v for v in values[12:] if v is not None]
    assert all(abs(v) < 1e-9 for v in non_none)


def test_rolling_mean_relative_volume_smooths_a_single_day_shock():
    """A ONE-DAY shock should show up much less in the rolling MEAN of
    RelativeVolume than a PERSISTENT cluster of the same peak height —
    the entire point of this feature."""
    one_day_shock = _spike_bars([1000] * 15 + [8000] + [1000] * 15)
    persistent_cluster = _spike_bars([1000] * 15 + [8000] * 10 + [1000] * 5)
    feature = RollingMeanRelativeVolume(base_window=10, lookback=10)
    shock_values = feature.compute(one_day_shock)
    cluster_values = feature.compute(persistent_cluster)
    shock_peak = max(v for v in shock_values if v is not None)
    cluster_peak = max(v for v in cluster_values if v is not None)
    assert cluster_peak > shock_peak


def test_log_relative_volume_matches_log_of_relative_volume():
    import math

    from src.features.volume import RelativeVolume

    bars = _spike_bars([1000] * 15 + [3000] * 5)
    rv = RelativeVolume(10).compute(bars)
    lrv = LogRelativeVolume(10).compute(bars)
    for a, b in zip(rv, lrv):
        if a is not None and a > 0:
            assert b is not None and abs(b - math.log(a)) < 1e-9
        else:
            assert b is None


def test_invalid_params_rejected():
    with pytest.raises(ValueError):
        VolumeZScore(window=1)
    with pytest.raises(ValueError):
        RollingFractionAboveThreshold(base_window=10, threshold=1.5, lookback=0)
    with pytest.raises(ValueError):
        RollingStdRelativeVolume(base_window=10, lookback=1)
