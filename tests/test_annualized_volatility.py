"""Phase 11: AnnualizedRealizedVolatility tests — confirms it's exactly
RealizedVolatility(window) * sqrt(252), with its own distinct column name,
and no-lookahead."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from src.data.bar import Bar
from src.features.annualized_volatility import TRADING_DAYS_PER_YEAR, AnnualizedRealizedVolatility
from src.features.volatility import RealizedVolatility


def _bars(n: int) -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    price = 100.0
    for i in range(n):
        price += 1.0 if i % 2 == 0 else -0.8
        bars.append(Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=price, high=price + 0.2, low=price - 0.2, close=max(price, 1.0), volume=1000))
    return bars


def test_name_is_distinct_from_raw_realized_vol():
    feature = AnnualizedRealizedVolatility(20)
    assert feature.spec.name == "realized_vol_20_ann"
    assert feature.spec.name != RealizedVolatility(20).spec.name


def test_values_match_raw_realized_vol_times_sqrt_252():
    bars = _bars(60)
    raw = RealizedVolatility(20).compute(bars)
    ann = AnnualizedRealizedVolatility(20).compute(bars)
    for r, a in zip(raw, ann):
        if r is None:
            assert a is None
        else:
            assert a is not None and abs(a - r * math.sqrt(TRADING_DAYS_PER_YEAR)) < 1e-9


def test_no_lookahead():
    base = _bars(80)
    mutated = list(base[:41]) + [
        Bar(timestamp=base[i].timestamp, symbol="AAPL", timeframe="day", open=1e9, high=2e9, low=5e8, close=1.5e9, volume=999)
        for i in range(41, 80)
    ]
    feature = AnnualizedRealizedVolatility(20)
    v_base, v_mut = feature.compute(base), feature.compute(mutated)
    for i in range(41):
        assert v_base[i] == v_mut[i]


def test_invalid_window_rejected():
    with pytest.raises(ValueError):
        AnnualizedRealizedVolatility(1)
