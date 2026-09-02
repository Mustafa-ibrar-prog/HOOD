"""Phase 12, Part 6 & 28: relative-strength feature tests — no-lookahead
(mirrors tests/test_feature_no_lookahead.py's methodology against every
feature in src/features/relative_strength.py) plus targeted correctness.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.bar import Bar
from src.features.momentum import RateOfChange
from src.features.relative_strength import RelativeStrengthAcceleration, RelativeStrengthPersistence, VolatilityAdjustedMomentum

CUTOFF = 100
TOTAL = 160


def _base_bars() -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    price = 100.0
    for i in range(TOTAL):
        price += (0.7 if i % 3 else -1.3) + (0.3 if i % 11 == 0 else 0.0)
        bars.append(Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=price - 0.2, high=price + 0.6, low=price - 0.8, close=max(price, 1.0), volume=1000))
    return bars


def _mutated_future(bars: list[Bar]) -> list[Bar]:
    out = list(bars[: CUTOFF + 1])
    start = bars[CUTOFF].timestamp
    for i in range(CUTOFF + 1, TOTAL):
        out.append(Bar(timestamp=start + timedelta(days=i - CUTOFF), symbol="AAPL", timeframe="day", open=1e9, high=2e9, low=5e8, close=1.5e9, volume=999_999_999))
    return out


FEATURES = [
    VolatilityAdjustedMomentum(momentum_window=20, vol_window=20),
    RelativeStrengthPersistence(momentum_window=20, lookback=20),
    RelativeStrengthAcceleration(momentum_window=20),
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


def _trend_bars(n: int, step: float) -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    price = 100.0
    for i in range(n):
        price += step
        bars.append(Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=price, high=price + 0.1, low=price - 0.1, close=max(price, 1.0), volume=1000))
    return bars


def test_vol_adjusted_momentum_matches_hand_computed_ratio():
    bars = _trend_bars(60, 0.5)
    feature = VolatilityAdjustedMomentum(momentum_window=20, vol_window=20)
    values = feature.compute(bars)
    mom = RateOfChange(20).compute(bars)
    from src.features.volatility import RealizedVolatility

    vol = RealizedVolatility(20).compute(bars)
    for v, m, vl in zip(values, mom, vol):
        if m is not None and vl is not None and vl != 0:
            assert v is not None and abs(v - m / vl) < 1e-9
        else:
            assert v is None


def test_relative_strength_persistence_is_one_for_a_sustained_uptrend():
    bars = _trend_bars(80, 1.0)  # strictly increasing -> RateOfChange(20) always positive once defined
    feature = RelativeStrengthPersistence(momentum_window=20, lookback=20)
    values = feature.compute(bars)
    non_none = [v for v in values if v is not None]
    assert non_none and non_none[-1] == 1.0


def test_relative_strength_persistence_is_zero_for_a_sustained_downtrend():
    bars = _trend_bars(80, -1.0)
    feature = RelativeStrengthPersistence(momentum_window=20, lookback=20)
    values = feature.compute(bars)
    non_none = [v for v in values if v is not None]
    assert non_none and non_none[-1] == 0.0


def test_relative_strength_acceleration_zero_for_linear_momentum_change():
    """A constant per-bar price STEP produces a roughly constant
    RateOfChange (momentum), so its own second difference should be ~0."""
    bars = _trend_bars(60, 2.0)
    feature = RelativeStrengthAcceleration(momentum_window=20)
    values = feature.compute(bars)
    non_none = [v for v in values if v is not None]
    assert non_none
    assert all(abs(v) < 0.5 for v in non_none[-10:])  # near-flat momentum in the steady-state region


def test_invalid_params_rejected():
    with pytest.raises(ValueError):
        VolatilityAdjustedMomentum(momentum_window=0)
    with pytest.raises(ValueError):
        RelativeStrengthPersistence(momentum_window=20, lookback=0)
