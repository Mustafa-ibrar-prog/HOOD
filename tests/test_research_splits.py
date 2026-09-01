"""Tests for chronological train/validation/test splitting — no shuffling,
no overlap, no future leaking into an earlier split."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.research.dataset import ResearchDataset
from src.research.splits import SplitConfig, SplitConfigError, chronological_split


def _dataset(dates: list[date]) -> ResearchDataset:
    rows = tuple({"timestamp": datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc), "symbol": "AAPL", "feature_x": 1.0, "target_y": 0.01} for d in dates)
    return ResearchDataset(symbol="AAPL", rows=rows, feature_columns=("feature_x",), target_columns=("target_y",), data_version="v", feature_version="v")


def test_split_buckets_rows_chronologically():
    dates = [date(2023, 1, 1), date(2023, 6, 1), date(2024, 3, 1), date(2024, 9, 1), date(2025, 1, 1)]
    ds = _dataset(dates)
    cfg = SplitConfig(
        train_start=date(2022, 1, 1), train_end=date(2023, 12, 31),
        validation_start=date(2024, 1, 1), validation_end=date(2024, 6, 30),
        test_start=date(2024, 7, 1), test_end=date(2025, 12, 31),
    )
    split = chronological_split(ds, cfg)
    assert len(split.train) == 2
    assert len(split.validation) == 1
    assert len(split.test) == 2
    assert split.dropped_count == 0


def test_rows_outside_every_range_are_dropped_not_included():
    dates = [date(2020, 1, 1), date(2023, 6, 1)]
    ds = _dataset(dates)
    cfg = SplitConfig(
        train_start=date(2023, 1, 1), train_end=date(2023, 12, 31),
        validation_start=date(2024, 1, 1), validation_end=date(2024, 6, 30),
        test_start=date(2024, 7, 1), test_end=date(2025, 12, 31),
    )
    split = chronological_split(ds, cfg)
    assert split.dropped_count == 1
    assert len(split.train) == 1


def test_config_rejects_overlapping_train_validation():
    with pytest.raises(SplitConfigError, match="train_end must be strictly before"):
        SplitConfig(
            train_start=date(2023, 1, 1), train_end=date(2024, 1, 1),
            validation_start=date(2023, 6, 1), validation_end=date(2024, 6, 1),
            test_start=date(2024, 7, 1), test_end=date(2025, 1, 1),
        )


def test_config_rejects_overlapping_validation_test():
    with pytest.raises(SplitConfigError, match="validation_end must be strictly before"):
        SplitConfig(
            train_start=date(2022, 1, 1), train_end=date(2022, 12, 31),
            validation_start=date(2023, 1, 1), validation_end=date(2024, 6, 1),
            test_start=date(2024, 1, 1), test_end=date(2025, 1, 1),
        )


def test_config_rejects_inverted_range():
    with pytest.raises(SplitConfigError):
        SplitConfig(
            train_start=date(2024, 1, 1), train_end=date(2023, 1, 1),
            validation_start=date(2024, 6, 1), validation_end=date(2024, 7, 1),
            test_start=date(2024, 8, 1), test_end=date(2024, 9, 1),
        )
