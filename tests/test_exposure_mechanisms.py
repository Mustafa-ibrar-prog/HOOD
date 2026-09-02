"""Phase 11, Parts 4-7, 25-26, 28: exposure-mechanism tests.
No-lookahead for compute_exposure_series (mirrors
tests/test_feature_no_lookahead.py's mutate-the-future methodology),
mechanism correctness (STATIC/VOL_TARGET/REGIME/COMPRESSION_EXPANSION),
bounds clamping, and shuffled/random placebo-series properties.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.bar import Bar
from src.research.exposure_mechanisms import (
    EXPOSURE_MAX,
    EXPOSURE_MIN,
    ExposureMechanismConfig,
    compute_exposure_series,
    random_exposure_series,
    shuffled_exposure_series,
)

TOTAL = 260
CUTOFF = 150


def _step_vol_bars(low_n: int, high_n: int, *, low_step: float = 0.1, high_step: float = 3.0) -> list[Bar]:
    """Oscillates STRICTLY around a fixed baseline (never cumulatively
    drifting) so rolling price-stdev reflects only the oscillation
    AMPLITUDE, not trend/level growth — a drifting cumulative-sum price
    path would make rolling stdev increase with level over a long enough
    series regardless of the intended low/high-vol segmentation."""
    import random as _random

    rng = _random.Random(12345)  # deterministic (reproducible), but NOT periodic like a modular pattern would be
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    baseline = 100.0
    n = low_n + high_n
    for i in range(n):
        base_amplitude = high_step if low_n <= i < low_n + high_n else low_step
        # small seeded jitter so rolling stdev isn't PERFECTLY constant within a segment (a
        # perfectly flat stdev series ties every percentile_rank comparison at "<=", which rounds
        # the tie up to the TOP bucket regardless of the segment's true level — an edge case of
        # the tie convention. A PERIODIC deterministic jitter whose period divides the rolling
        # window evenly reproduces the exact same artifact — hence a genuinely non-periodic,
        # seeded jitter here instead.)
        amplitude = base_amplitude * (1.0 + 0.2 * rng.random())
        price = baseline + (amplitude if i % 2 == 0 else -amplitude)
        bars.append(Bar(timestamp=start + timedelta(days=i), symbol="SPY", timeframe="day", open=price, high=price + 0.2, low=price - 0.2, close=max(price, 1.0), volume=1000))
    return bars


def _base_bars() -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    price = 100.0
    for i in range(TOTAL):
        block = (i // 20) % 2
        step = 0.15 if block == 0 else 2.5
        price += step if i % 2 == 0 else -step * 0.9
        bars.append(Bar(timestamp=start + timedelta(days=i), symbol="SPY", timeframe="day", open=price - 0.1, high=price + 0.3, low=price - 0.3, close=max(price, 1.0), volume=1000))
    return bars


def _mutated_future(bars: list[Bar]) -> list[Bar]:
    out = list(bars[: CUTOFF + 1])
    start = bars[CUTOFF].timestamp
    for i in range(CUTOFF + 1, TOTAL):
        out.append(Bar(timestamp=start + timedelta(days=i - CUTOFF), symbol="SPY", timeframe="day", open=1e9, high=2e9, low=5e8, close=1.5e9, volume=999_999_999))
    return out


CONFIGS = [
    ExposureMechanismConfig(mechanism="STATIC", rebalance_frequency="daily"),
    ExposureMechanismConfig(mechanism="VOL_TARGET", target_annual_vol=0.15, rebalance_frequency="weekly"),
    ExposureMechanismConfig(mechanism="REGIME", rebalance_frequency="weekly"),
    ExposureMechanismConfig(mechanism="COMPRESSION_EXPANSION", rebalance_frequency="weekly"),
]


@pytest.mark.parametrize("config", CONFIGS, ids=lambda c: c.label)
def test_compute_exposure_series_does_not_leak_future_data(config):
    base = _base_bars()
    mutated = _mutated_future(base)
    series_base = compute_exposure_series(base, config)
    series_mutated = compute_exposure_series(mutated, config)
    cutoff_ts = base[CUTOFF].timestamp
    for ts, value in series_base.items():
        if ts <= cutoff_ts and ts in series_mutated:
            assert series_mutated[ts] == value, f"{config.label} leaked future data at {ts}"


def test_static_is_always_max_exposure():
    bars = _step_vol_bars(60, 30)
    config = ExposureMechanismConfig(mechanism="STATIC", rebalance_frequency="daily")
    series = compute_exposure_series(bars, config)
    assert series  # produced something
    assert all(v == EXPOSURE_MAX for v in series.values())


def test_vol_target_reduces_exposure_when_forecast_exceeds_target():
    bars = _step_vol_bars(60, 40, high_step=4.0)
    config = ExposureMechanismConfig(mechanism="VOL_TARGET", target_annual_vol=0.15, rebalance_frequency="daily")
    series = compute_exposure_series(bars, config)
    timestamps = sorted(series.keys())
    late_high_vol_values = [series[ts] for ts in timestamps if ts >= bars[85].timestamp]
    assert late_high_vol_values and min(late_high_vol_values) < EXPOSURE_MAX  # high vol -> reduced exposure at some point


def test_vol_target_clamped_to_bounds():
    bars = _step_vol_bars(60, 40, high_step=8.0)  # extreme vol -> raw exposure would be far below EXPOSURE_MIN
    config = ExposureMechanismConfig(mechanism="VOL_TARGET", target_annual_vol=0.15, rebalance_frequency="daily")
    series = compute_exposure_series(bars, config)
    assert series
    assert all(EXPOSURE_MIN <= v <= EXPOSURE_MAX for v in series.values())


def test_regime_mechanism_reduces_exposure_in_high_vol_regime():
    bars = _step_vol_bars(150, 80)
    config = ExposureMechanismConfig(mechanism="REGIME", rebalance_frequency="daily")
    series = compute_exposure_series(bars, config)
    values = list(series.values())
    assert values
    assert min(values) < EXPOSURE_MAX  # some regime reduced exposure below full
    assert max(values) == EXPOSURE_MAX  # some regime stayed at full


def test_compression_expansion_mechanism_values_are_only_the_preregistered_three():
    bars = _step_vol_bars(150, 80)
    config = ExposureMechanismConfig(mechanism="COMPRESSION_EXPANSION", rebalance_frequency="weekly")
    series = compute_exposure_series(bars, config)
    assert series
    assert set(series.values()) <= {1.00, 0.50}


def test_rebalance_frequency_controls_how_many_timestamps_are_produced():
    bars = _step_vol_bars(150, 80)
    daily = compute_exposure_series(bars, ExposureMechanismConfig(mechanism="STATIC", rebalance_frequency="daily"))
    weekly = compute_exposure_series(bars, ExposureMechanismConfig(mechanism="STATIC", rebalance_frequency="weekly"))
    assert len(daily) > len(weekly)
    assert len(daily) >= 4 * len(weekly) - 5  # roughly 5x fewer, allowing slack


def test_invalid_mechanism_or_missing_target_vol_rejected():
    with pytest.raises(ValueError):
        ExposureMechanismConfig(mechanism="NOT_A_MECHANISM")
    with pytest.raises(ValueError):
        ExposureMechanismConfig(mechanism="VOL_TARGET")  # missing target_annual_vol
    with pytest.raises(ValueError):
        ExposureMechanismConfig(mechanism="STATIC", rebalance_frequency="monthly")  # not a preregistered frequency


# --- placebo/shuffled series properties (Parts 25-26) ----------------------------------------


def test_shuffled_series_preserves_timestamps_and_value_multiset():
    bars = _step_vol_bars(150, 80)
    real = compute_exposure_series(bars, ExposureMechanismConfig(mechanism="REGIME", rebalance_frequency="weekly"))
    shuffled = shuffled_exposure_series(real, seed=1)
    assert set(shuffled.keys()) == set(real.keys())
    assert sorted(shuffled.values()) == sorted(real.values())  # exact same multiset, different assignment


def test_shuffled_series_actually_changes_the_temporal_assignment():
    bars = _step_vol_bars(150, 80)
    real = compute_exposure_series(bars, ExposureMechanismConfig(mechanism="REGIME", rebalance_frequency="weekly"))
    shuffled = shuffled_exposure_series(real, seed=1)
    # with a reasonably large, non-constant series, a random permutation should differ somewhere
    assert any(shuffled[k] != real[k] for k in real) or len(set(real.values())) <= 1


def test_random_series_preserves_timestamps_and_bounds():
    bars = _step_vol_bars(150, 80)
    real = compute_exposure_series(bars, ExposureMechanismConfig(mechanism="VOL_TARGET", target_annual_vol=0.15, rebalance_frequency="weekly"))
    randomized = random_exposure_series(real, seed=2)
    assert set(randomized.keys()) == set(real.keys())
    lo, hi = min(real.values()), max(real.values())
    assert all(lo <= v <= hi for v in randomized.values())  # drawn FROM the real distribution, so bounded by it


def test_shuffled_and_random_are_deterministic_given_a_seed():
    bars = _step_vol_bars(150, 80)
    real = compute_exposure_series(bars, ExposureMechanismConfig(mechanism="REGIME", rebalance_frequency="weekly"))
    assert shuffled_exposure_series(real, seed=7) == shuffled_exposure_series(real, seed=7)
    assert random_exposure_series(real, seed=7) == random_exposure_series(real, seed=7)
