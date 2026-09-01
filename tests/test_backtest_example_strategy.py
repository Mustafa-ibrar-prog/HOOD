"""Tests for the example moving-average crossover strategy (Phase 3,
section 23) — proves its on_bar() logic in isolation, hand-verifiable."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.backtesting.example_strategy import MovingAverageCrossoverStrategy
from src.data.bar import Bar


def _bars(closes: list[float]):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=c, high=c + 1, low=c - 1, close=c, volume=100)
        for i, c in enumerate(closes)
    ]


def test_rejects_fast_window_not_less_than_slow():
    with pytest.raises(ValueError):
        MovingAverageCrossoverStrategy(fast_window=20, slow_window=10)


def test_returns_none_when_features_missing():
    strategy = MovingAverageCrossoverStrategy(fast_window=3, slow_window=5)
    signal = strategy.on_bar(_bars([100.0]), {"sma_3": None, "sma_5": None})
    assert signal is None


def test_long_signal_when_fast_above_slow():
    strategy = MovingAverageCrossoverStrategy(fast_window=3, slow_window=5)
    signal = strategy.on_bar(_bars([100.0]), {"sma_3": 105.0, "sma_5": 100.0})
    assert signal.direction == "LONG"


def test_flat_signal_when_fast_at_or_below_slow():
    strategy = MovingAverageCrossoverStrategy(fast_window=3, slow_window=5)
    signal = strategy.on_bar(_bars([100.0]), {"sma_3": 100.0, "sma_5": 100.0})
    assert signal.direction == "FLAT"
    signal2 = strategy.on_bar(_bars([100.0]), {"sma_3": 95.0, "sma_5": 100.0})
    assert signal2.direction == "FLAT"


def test_feature_engine_produces_the_features_this_strategy_expects():
    strategy = MovingAverageCrossoverStrategy(fast_window=3, slow_window=5)
    engine = strategy.feature_engine()
    bars = _bars([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
    frame = engine.compute(bars)
    assert "sma_3" in frame.feature_names
    assert "sma_5" in frame.feature_names
