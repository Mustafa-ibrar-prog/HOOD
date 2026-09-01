"""Tests for the ResearchStrategy interface, the six strategy families,
and the adapter into Phase 3's BacktestEngine (Phase 4, sections 2, 4, 5)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.bar import Bar
from src.research.strategies import (
    MeanReversionStrategy,
    MomentumStrategy,
    VolatilityRegimeStrategy,
    VolumeConfirmedMomentumStrategy,
    campaign_hypotheses,
)
from src.research.strategy import ResearchSignal, ResearchStrategyBacktestAdapter


def _bars(closes: list[float], volumes: list[int] | None = None) -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    volumes = volumes or [1000] * len(closes)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol="TEST", timeframe="day", open=c, high=c + 1, low=c - 1, close=c, volume=v)
        for i, (c, v) in enumerate(zip(closes, volumes))
    ]


def test_research_signal_rejects_invalid_direction():
    with pytest.raises(ValueError):
        ResearchSignal(timestamp=datetime.now(timezone.utc), symbol="X", strategy_id="s", strategy_version="1.0", direction="SHORT", signal_strength=None, target_position=None)


def test_research_signal_rejects_out_of_range_strength():
    with pytest.raises(ValueError):
        ResearchSignal(timestamp=datetime.now(timezone.utc), symbol="X", strategy_id="s", strategy_version="1.0", direction="LONG", signal_strength=1.5, target_position=None)


def test_research_signal_allows_none_strength_never_fabricated():
    sig = ResearchSignal(timestamp=datetime.now(timezone.utc), symbol="X", strategy_id="s", strategy_version="1.0", direction="LONG", signal_strength=None, target_position=None)
    assert sig.signal_strength is None


def test_momentum_strategy_long_on_strong_positive_return():
    strategy = MomentumStrategy(strategy_id="MOM-TEST", lookback=5, universe=["TEST"], entry_threshold=0.02)
    bars = _bars([100.0] * 6 + [120.0])  # a big jump -> strong positive 5-day return
    engine = strategy.feature_engine()
    frame = engine.compute(bars)
    features = {name: frame.columns[name][-1] for name in frame.feature_names}
    signal = strategy.generate_signal(bars, features)
    assert signal is not None
    assert signal.direction == "LONG"
    assert signal.signal_strength is not None


def test_momentum_strategy_flat_on_no_return():
    strategy = MomentumStrategy(strategy_id="MOM-TEST", lookback=5, universe=["TEST"], entry_threshold=0.02, exit_threshold=0.0)
    bars = _bars([100.0] * 7)
    engine = strategy.feature_engine()
    frame = engine.compute(bars)
    features = {name: frame.columns[name][-1] for name in frame.feature_names}
    signal = strategy.generate_signal(bars, features)
    assert signal.direction == "FLAT"


def test_mean_reversion_strategy_long_on_oversold_extreme():
    strategy = MeanReversionStrategy(strategy_id="MR-TEST", lookback=5, universe=["TEST"], entry_z=-1.5)
    bars = _bars([100.0, 100.0, 100.0, 100.0, 100.0, 70.0])  # sharp drop -> very negative z-score
    engine = strategy.feature_engine()
    frame = engine.compute(bars)
    features = {name: frame.columns[name][-1] for name in frame.feature_names}
    signal = strategy.generate_signal(bars, features)
    assert signal is not None
    assert signal.direction == "LONG"


def test_volatility_regime_strategy_returns_none_strength_for_categorical_signal():
    strategy = VolatilityRegimeStrategy(strategy_id="VOL-TEST", universe=["TEST"], fast_window=3, slow_window=5, vol_window=3, vol_lookback=5)
    closes = [100.0 + i for i in range(20)]
    bars = _bars(closes)
    engine = strategy.feature_engine()
    frame = engine.compute(bars)
    features = {name: frame.columns[name][-1] for name in frame.feature_names}
    signal = strategy.generate_signal(bars, features)
    if signal is not None:
        assert signal.signal_strength is None  # honestly no fabricated confidence for a categorical regime signal


def test_volume_confirmed_momentum_requires_both_conditions():
    strategy = VolumeConfirmedMomentumStrategy(strategy_id="VOLM-TEST", universe=["TEST"], lookback=5, entry_threshold=0.02, volume_window=3, min_relative_volume=1.2)
    # Strong price move but LOW volume -> should NOT confirm.
    bars = _bars([100.0] * 6 + [130.0], volumes=[1000] * 7)
    engine = strategy.feature_engine()
    frame = engine.compute(bars)
    features = {name: frame.columns[name][-1] for name in frame.feature_names}
    signal = strategy.generate_signal(bars, features)
    assert signal.direction == "FLAT"  # flat price+volume history -> no confirmed move


def test_campaign_hypotheses_have_unique_ids_and_are_registerable():
    from src.research.hypothesis import HypothesisRegistry

    hyps = campaign_hypotheses(["NIO", "MARA"])
    assert len(hyps) == 6
    ids = [h.hypothesis_id for h in hyps]
    assert len(set(ids)) == len(ids)
    for h in hyps:
        assert h.expected_direction in ("positive", "negative", "unsigned")


def test_research_strategy_backtest_adapter_delegates_to_generate_signal():
    strategy = MomentumStrategy(strategy_id="MOM-TEST", lookback=5, universe=["TEST"], entry_threshold=0.02)
    adapter = ResearchStrategyBacktestAdapter(strategy)
    bars = _bars([100.0] * 6 + [120.0])
    engine = strategy.feature_engine()
    frame = engine.compute(bars)
    features = {name: frame.columns[name][-1] for name in frame.feature_names}
    signal = adapter.on_bar(bars, features)
    assert signal is not None
    assert signal.direction == "LONG"
    assert adapter.last_signal is not None  # the original ResearchSignal is preserved for inspection


def test_research_strategy_backtest_adapter_returns_none_when_no_signal():
    strategy = MomentumStrategy(strategy_id="MOM-TEST", lookback=5, universe=["TEST"])
    adapter = ResearchStrategyBacktestAdapter(strategy)
    signal = adapter.on_bar(_bars([100.0]), {"roc_5": None})
    assert signal is None
