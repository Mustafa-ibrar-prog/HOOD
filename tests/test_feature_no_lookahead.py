"""THE critical test for Phase 2, section 6: verify that no feature in
this codebase ever uses future data.

Method (exactly as specified): build a series, compute every registered
feature over it, then replace everything AFTER a cutoff index with
extreme/huge synthetic values and recompute. If any feature's value at or
before the cutoff changes, that feature is leaking future information —
this test fails immediately and names the offending feature.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.bar import Bar
from src.features.mean_reversion import DistanceFromMA, RollingZScore, StandardizedReturns
from src.features.momentum import Momentum, MovingAverage, MovingAverageDistance, RateOfChange
from src.features.price import CumulativeReturn, LogReturn, RollingReturn, SimpleReturn
from src.features.regime import MomentumRegime, TrendRegime, VolatilityRegime
from src.features.relationship import relative_strength, rolling_beta, rolling_correlation
from src.features.volatility import ATR, RealizedVolatility, RollingStd, VolatilityPercentile
from src.features.volume import RelativeVolume, RollingVolume, VolumeChange, VolumePercentile

CUTOFF = 100
TOTAL = 160


def _base_bars() -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    price = 100.0
    for i in range(TOTAL):
        price += (0.7 if i % 3 else -1.3)
        bars.append(
            Bar(
                timestamp=start + timedelta(days=i),
                symbol="AAPL",
                timeframe="day",
                open=price - 0.2,
                high=price + 0.6,
                low=price - 0.8,
                close=price,
                volume=1000 + (i * 37) % 500,
            )
        )
    return bars


def _mutated_future(bars: list[Bar]) -> list[Bar]:
    """Same as _base_bars() up to CUTOFF (inclusive); everything after is
    replaced with extreme, obviously-different values."""
    out = list(bars[: CUTOFF + 1])
    start = bars[CUTOFF].timestamp
    for i in range(CUTOFF + 1, TOTAL):
        offset = i - CUTOFF
        out.append(
            Bar(
                timestamp=start + timedelta(days=offset),
                symbol="AAPL",
                timeframe="day",
                open=1_000_000_000.0,
                high=2_000_000_000.0,
                low=500_000_000.0,
                close=1_500_000_000.0,
                volume=999_999_999,
            )
        )
    return out


FEATURES = [
    SimpleReturn(5),
    LogReturn(5),
    CumulativeReturn(),
    RollingReturn(10),
    Momentum(10),
    RateOfChange(10),
    MovingAverage(20),
    MovingAverageDistance(20),
    RollingStd(20),
    RealizedVolatility(20),
    ATR(14),
    VolatilityPercentile(window=10, lookback=30),
    RollingVolume(20),
    VolumeChange(5),
    RelativeVolume(20),
    VolumePercentile(window=10, lookback=30),
    RollingZScore(20),
    DistanceFromMA(20),
    StandardizedReturns(window=20, return_period=5),
    TrendRegime(fast_window=10, slow_window=30),
    VolatilityRegime(window=10, lookback=30),
    MomentumRegime(period=10),
]


@pytest.mark.parametrize("feature", FEATURES, ids=lambda f: f.spec.name)
def test_feature_does_not_leak_future_data(feature):
    base = _base_bars()
    mutated = _mutated_future(base)

    values_base = feature.compute(base)
    values_mutated = feature.compute(mutated)

    # Every value at or before CUTOFF must be identical regardless of what
    # happens to the data after it.
    for i in range(CUTOFF + 1):
        assert values_base[i] == values_mutated[i], (
            f"{feature.spec.name} leaked future data at index {i}: "
            f"{values_base[i]!r} (real future) != {values_mutated[i]!r} (mutated future)"
        )


def test_relationship_functions_do_not_leak_future_data():
    base = _base_bars()
    mutated = _mutated_future(base)
    closes_base = [b.close for b in base]
    closes_mutated = [b.close for b in mutated]
    # A second, unrelated series used as "b" in the pairwise functions —
    # also gets its future mutated identically to isolate the leakage check
    # to "does index i ever depend on index > i", not just series a's tail.
    other_base = [50.0 + 0.3 * i for i in range(TOTAL)]
    other_mutated = other_base[: CUTOFF + 1] + [999_999.0] * (TOTAL - CUTOFF - 1)

    for fn in (
        lambda a, b, w: rolling_correlation(a, b, w),
        lambda a, b, w: rolling_beta(a, b, w),
        lambda a, b, w: relative_strength(a, b, w),
    ):
        result_base = fn(closes_base, other_base, 20)
        result_mutated = fn(closes_mutated, other_mutated, 20)
        for i in range(CUTOFF + 1):
            assert result_base[i] == result_mutated[i], f"{fn} leaked future data at index {i}"


def test_synthetic_leakage_scenario_actually_changes_the_tail():
    """Sanity-check the test harness itself: the mutated series must
    actually differ after the cutoff (otherwise the leakage test above
    would be vacuously true)."""
    base = _base_bars()
    mutated = _mutated_future(base)
    assert base[CUTOFF + 1].close != mutated[CUTOFF + 1].close
    assert mutated[CUTOFF + 1].close > 1_000_000.0
