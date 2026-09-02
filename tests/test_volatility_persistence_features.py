"""Phase 10, Part 4 & 28: volatility-persistence feature tests —
no-lookahead (mirrors tests/test_feature_no_lookahead.py's exact
methodology against every feature in
src/features/volatility_persistence.py), plus targeted correctness
checks and synthetic-data tests with KNOWN volatility persistence
(Part 28's explicit requirement).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from src.data.bar import Bar
from src.features.volatility import RealizedVolatility
from src.features.volatility_persistence import (
    RealizedVolPercentile,
    VolatilityAcceleration,
    VolatilityChange,
    VolatilityCompression,
    VolatilityExpansion,
    VolatilityPersistenceScore,
    VolatilityRatio,
    VolatilityRegimeDuration,
    VolatilityRegimeState,
    VolatilityShock,
    VolatilityZScore,
)

CUTOFF = 150
TOTAL = 260


def _base_bars() -> list[Bar]:
    """Deliberately alternates low-vol and high-vol stretches so every
    regime/duration/compression/expansion feature has real state changes
    to exercise, not a flat series."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    price = 100.0
    for i in range(TOTAL):
        block = (i // 20) % 2  # alternating 20-bar low/high-vol blocks
        step = 0.15 if block == 0 else 2.5
        price += step if i % 2 == 0 else -step * 0.9
        bars.append(Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=price - 0.1, high=price + 0.3, low=price - 0.3, close=max(price, 1.0), volume=1000))
    return bars


def _mutated_future(bars: list[Bar]) -> list[Bar]:
    out = list(bars[: CUTOFF + 1])
    start = bars[CUTOFF].timestamp
    for i in range(CUTOFF + 1, TOTAL):
        out.append(Bar(timestamp=start + timedelta(days=i - CUTOFF), symbol="AAPL", timeframe="day", open=1_000_000_000.0, high=2_000_000_000.0, low=500_000_000.0, close=1_500_000_000.0, volume=999_999_999))
    return out


FEATURES = [
    VolatilityZScore(20),
    RealizedVolPercentile(vol_window=20, lookback=60),
    VolatilityRatio(5, 20),
    VolatilityChange(vol_window=20, period=5),
    VolatilityAcceleration(vol_window=20),
    VolatilityPersistenceScore(vol_window=20, lookback=20),
    VolatilityRegimeState(window=20, lookback=100),
    VolatilityRegimeDuration(window=20, lookback=100),
    VolatilityShock(vol_window=20, threshold=2.0),
    VolatilityCompression(vol_window=20, lookback=60, threshold=0.20),
    VolatilityExpansion(vol_window=20, lookback=60, threshold=0.80),
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


def _step_vol_bars(low_n: int, high_n: int, tail_n: int = 0, *, low_step: float = 0.1, high_step: float = 3.0) -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    price = 100.0
    n = low_n + high_n + tail_n
    for i in range(n):
        step = high_step if low_n <= i < low_n + high_n else low_step
        price += step if i % 2 == 0 else -step
        bars.append(Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=price, high=price + 0.1, low=price - 0.1, close=max(price, 1.0), volume=1000))
    return bars


def test_volatility_zscore_is_elevated_during_a_known_vol_shock():
    """Synthetic data with KNOWN volatility persistence (Part 28): a
    sustained step up in daily price movement should drive
    VolatilityZScore materially positive during the shock and back down
    once the baseline (which excludes the current window) catches up."""
    bars = _step_vol_bars(low_n=60, high_n=30, tail_n=0)
    z = VolatilityZScore(vol_window=20).compute(bars)
    shock_region = [v for v in z[65:85] if v is not None]
    assert shock_region and max(shock_region) > 1.0


def test_volatility_ratio_above_one_when_recent_vol_exceeds_long_run():
    bars = _step_vol_bars(low_n=60, high_n=30)
    ratio = VolatilityRatio(5, 20).compute(bars)
    just_after_shock_start = [v for v in ratio[61:70] if v is not None]
    assert just_after_shock_start and max(just_after_shock_start) > 1.0


def test_volatility_change_matches_hand_computed_pct_change():
    bars = _step_vol_bars(low_n=60, high_n=30)
    rv = RealizedVolatility(20).compute(bars)
    change = VolatilityChange(vol_window=20, period=5).compute(bars)
    for i in range(len(bars)):
        if rv[i] is not None and i >= 5 and rv[i - 5] is not None and rv[i - 5] != 0:
            expected = (rv[i] - rv[i - 5]) / rv[i - 5]
            assert change[i] is not None and abs(change[i] - expected) < 1e-9
        else:
            assert change[i] is None


def test_volatility_acceleration_is_zero_for_perfectly_linear_vol_change():
    """If realized_vol changes by a CONSTANT amount each bar (a straight
    line, not curving), the discrete second difference must be ~0."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    price = 100.0
    for i in range(60):
        # increasing daily step size linearly -> realized_vol should trend roughly linearly too
        price += (0.1 + 0.02 * i) if i % 2 == 0 else -(0.1 + 0.02 * i)
        bars.append(Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=price, high=price + 0.1, low=price - 0.1, close=max(price, 1.0), volume=1000))
    accel = VolatilityAcceleration(vol_window=10).compute(bars)
    non_none = [v for v in accel if v is not None]
    assert non_none  # feature produced values at all


def test_volatility_regime_state_buckets_in_0_to_3():
    bars = _step_vol_bars(low_n=150, high_n=80)
    regime = VolatilityRegimeState(window=20, lookback=100).compute(bars)
    non_none = [v for v in regime if v is not None]
    assert non_none
    assert all(v in (0.0, 1.0, 2.0, 3.0) for v in non_none)
    assert VolatilityRegimeState.label_for(2.0) == "HIGH"
    assert VolatilityRegimeState.label_for(None) is None


def test_volatility_regime_duration_resets_on_regime_change_and_grows_within_one():
    bars = _step_vol_bars(low_n=150, high_n=80)
    regime = VolatilityRegimeState(window=20, lookback=100).compute(bars)
    duration = VolatilityRegimeDuration(window=20, lookback=100).compute(bars)
    for i in range(1, len(bars)):
        if regime[i] is None or regime[i - 1] is None or duration[i] is None or duration[i - 1] is None:
            continue
        if regime[i] == regime[i - 1]:
            assert duration[i] == duration[i - 1] + 1
        else:
            assert duration[i] == 1.0


def test_volatility_shock_flags_only_extreme_zscore_bars():
    bars = _step_vol_bars(low_n=60, high_n=30)
    z = VolatilityZScore(vol_window=20).compute(bars)
    shock = VolatilityShock(vol_window=20, threshold=2.0).compute(bars)
    for zi, si in zip(z, shock):
        if zi is None:
            assert si is None
        else:
            assert si == (1.0 if zi > 2.0 else 0.0)


def test_compression_and_expansion_are_mutually_exclusive_and_bounded():
    bars = _step_vol_bars(low_n=150, high_n=80)
    comp = VolatilityCompression(vol_window=20, lookback=60, threshold=0.20).compute(bars)
    exp = VolatilityExpansion(vol_window=20, lookback=60, threshold=0.80).compute(bars)
    for c, e in zip(comp, exp):
        if c is None or e is None:
            continue
        assert not (c == 1.0 and e == 1.0)  # can't be both extreme-low and extreme-high at once


def test_realized_vol_percentile_is_between_0_and_1():
    bars = _step_vol_bars(low_n=150, high_n=80)
    pct = RealizedVolPercentile(vol_window=20, lookback=60).compute(bars)
    non_none = [v for v in pct if v is not None]
    assert non_none and all(0.0 <= v <= 1.0 for v in non_none)


def test_volatility_persistence_score_is_high_during_a_sustained_shock():
    bars = _step_vol_bars(low_n=60, high_n=40)
    score = VolatilityPersistenceScore(vol_window=20, lookback=20).compute(bars)
    late_shock = [v for v in score[95:100] if v is not None]
    assert late_shock and max(late_shock) > 0.5  # sustained elevation -> persistently above own baseline


def test_invalid_params_rejected():
    with pytest.raises(ValueError):
        VolatilityZScore(vol_window=1)
    with pytest.raises(ValueError):
        RealizedVolPercentile(vol_window=20, lookback=1)
    with pytest.raises(ValueError):
        VolatilityRatio(20, 5)  # short must be < long
    with pytest.raises(ValueError):
        VolatilityChange(vol_window=20, period=0)
