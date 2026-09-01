"""Tests for FeatureEngine: registration, manifest, alignment, and its
own input-validation guarantees."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.bar import Bar
from src.features import FeatureEngine
from src.features.momentum import Momentum, MovingAverage


def _bars(symbol="AAPL", n=30):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol=symbol, timeframe="day", open=100 + i, high=101 + i, low=99 + i, close=100 + i, volume=100)
        for i in range(n)
    ]


def test_engine_computes_all_registered_features():
    engine = FeatureEngine([Momentum(5), MovingAverage(10)])
    frame = engine.compute(_bars())
    assert set(frame.feature_names) == {"momentum_5", "sma_10"}
    assert len(frame.columns["momentum_5"]) == 30
    assert len(frame.columns["sma_10"]) == 30


def test_engine_rejects_duplicate_feature_names():
    with pytest.raises(ValueError, match="unique feature names"):
        FeatureEngine([Momentum(5), Momentum(5)])


def test_engine_manifest_captures_name_version_params():
    engine = FeatureEngine([Momentum(5)])
    manifest = engine.manifest()
    assert manifest[0]["name"] == "momentum_5"
    assert manifest[0]["params"] == {"period": 5}
    assert manifest[0]["version"] == "1.0"


def test_engine_rejects_empty_bars():
    engine = FeatureEngine([Momentum(5)])
    with pytest.raises(ValueError, match="at least one bar"):
        engine.compute([])


def test_engine_rejects_mixed_symbols():
    bars = _bars("AAA", 5) + _bars("BBB", 5)
    engine = FeatureEngine([Momentum(2)])
    with pytest.raises(ValueError, match="single symbol"):
        engine.compute(bars)


def test_engine_rejects_non_ascending_timestamps():
    bars = list(reversed(_bars(n=5)))
    engine = FeatureEngine([Momentum(2)])
    with pytest.raises(ValueError, match="ascending"):
        engine.compute(bars)


def test_frame_to_rows_aligns_timestamp_and_symbol():
    engine = FeatureEngine([Momentum(2)])
    frame = engine.compute(_bars(n=5))
    rows = frame.to_rows()
    assert len(rows) == 5
    assert rows[0]["symbol"] == "AAPL"
    assert "momentum_2" in rows[0]
