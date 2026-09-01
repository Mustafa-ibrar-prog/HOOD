"""Tests for ResearchDatasetGenerator: feature/target column separation
and correct alignment."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.bar import Bar
from src.features import FeatureEngine
from src.features.momentum import Momentum
from src.research.dataset import FEATURE_PREFIX, TARGET_PREFIX, ResearchDatasetGenerator


def _bars(n=60):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    price = 100.0
    bars = []
    for i in range(n):
        price += 0.5
        bars.append(Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=price, high=price + 1, low=price - 1, close=price, volume=100))
    return bars


def test_feature_and_target_columns_are_distinctly_prefixed():
    engine = FeatureEngine([Momentum(5)])
    gen = ResearchDatasetGenerator(engine, horizons=(1, 5))
    ds = gen.generate(_bars(), data_version="v1")
    assert all(c.startswith(FEATURE_PREFIX) for c in ds.feature_columns)
    assert all(c.startswith(TARGET_PREFIX) for c in ds.target_columns)
    assert set(ds.feature_columns).isdisjoint(ds.target_columns)


def test_rows_carry_both_feature_and_target_values():
    engine = FeatureEngine([Momentum(5)])
    gen = ResearchDatasetGenerator(engine, horizons=(1,))
    ds = gen.generate(_bars(), data_version="v1")
    row = ds.rows[10]
    assert "feature_momentum_5" in row
    assert "target_future_return_1bar" in row
    assert row["timestamp"] is not None
    assert row["symbol"] == "AAPL"


def test_target_is_none_at_the_end_of_the_series():
    engine = FeatureEngine([Momentum(5)])
    gen = ResearchDatasetGenerator(engine, horizons=(20,))
    ds = gen.generate(_bars(n=30), data_version="v1")
    assert ds.rows[-1]["target_future_return_20bar"] is None


def test_data_version_and_feature_version_are_recorded():
    engine = FeatureEngine([Momentum(5)])
    gen = ResearchDatasetGenerator(engine)
    ds = gen.generate(_bars(), data_version="my-data-version")
    assert ds.data_version == "my-data-version"
    assert "momentum_5:1.0" in ds.feature_version


def test_generate_rejects_empty_bars():
    engine = FeatureEngine([Momentum(5)])
    gen = ResearchDatasetGenerator(engine)
    with pytest.raises(ValueError):
        gen.generate([], data_version="v1")
