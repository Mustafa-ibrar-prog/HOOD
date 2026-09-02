"""Phase 11, Part 9, 28: PrecomputedExposureStrategy tests — signal
generation only at precomputed timestamps, None elsewhere (rebalance-day
semantics), defensive bounds check.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.bar import Bar
from src.research.exposure_strategy import PrecomputedExposureStrategy


def _bars(n: int, symbol: str = "SPY") -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [Bar(timestamp=start + timedelta(days=i), symbol=symbol, timeframe="day", open=100 + i, high=101 + i, low=99 + i, close=100 + i, volume=1000) for i in range(n)]


def test_emits_a_signal_only_at_precomputed_timestamps():
    bars = _bars(10)
    exposure_by_symbol = {"SPY": {bars[2].timestamp: 0.5, bars[6].timestamp: 0.8}}
    strategy = PrecomputedExposureStrategy(strategy_id="TEST", exposure_by_symbol=exposure_by_symbol, universe=["SPY"], hypothesis_id="P11-VCE-TEST")
    for i, bar in enumerate(bars):
        signal = strategy.generate_signal(bars[: i + 1], {})
        if bar.timestamp in exposure_by_symbol["SPY"]:
            assert signal is not None
            assert signal.direction == "LONG"
            assert signal.signal_strength == exposure_by_symbol["SPY"][bar.timestamp]
        else:
            assert signal is None


def test_unknown_symbol_returns_none():
    bars = _bars(5)
    strategy = PrecomputedExposureStrategy(strategy_id="TEST", exposure_by_symbol={}, universe=["SPY"], hypothesis_id="P11-VCE-TEST")
    assert strategy.generate_signal(bars, {}) is None


def test_out_of_bounds_exposure_raises_rather_than_silently_clamping():
    bars = _bars(3)
    exposure_by_symbol = {"SPY": {bars[1].timestamp: 1.5}}  # invalid — a bug in whatever produced this
    strategy = PrecomputedExposureStrategy(strategy_id="TEST", exposure_by_symbol=exposure_by_symbol, universe=["SPY"], hypothesis_id="P11-VCE-TEST")
    strategy.generate_signal(bars[:1], {})  # timestamp 0 — no signal, fine
    with pytest.raises(ValueError):
        strategy.generate_signal(bars[:2], {})


def test_feature_engine_is_empty_since_exposure_is_precomputed():
    strategy = PrecomputedExposureStrategy(strategy_id="TEST", exposure_by_symbol={}, universe=["SPY"], hypothesis_id="P11-VCE-TEST")
    engine = strategy.feature_engine()
    assert engine.manifest() == []
