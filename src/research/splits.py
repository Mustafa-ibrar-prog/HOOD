"""Time-series-safe train/validation/test splitting.

NEVER shuffle financial time-series data for an ordinary split — that
leaks future information into "earlier" folds and produces a backtest
that looks far better than any strategy actually is. This module only
ever buckets rows by chronological date range.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.research.dataset import ResearchDataset


class SplitConfigError(ValueError):
    """Raised when a SplitConfig's date ranges are not chronological and
    non-overlapping — the one invariant this module refuses to relax."""


@dataclass(frozen=True)
class SplitConfig:
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date

    def __post_init__(self) -> None:
        if self.train_start > self.train_end:
            raise SplitConfigError("train_start must be <= train_end")
        if self.validation_start > self.validation_end:
            raise SplitConfigError("validation_start must be <= validation_end")
        if self.test_start > self.test_end:
            raise SplitConfigError("test_start must be <= test_end")
        if self.train_end >= self.validation_start:
            raise SplitConfigError(
                "train_end must be strictly before validation_start — splits must be chronological and non-overlapping"
            )
        if self.validation_end >= self.test_start:
            raise SplitConfigError(
                "validation_end must be strictly before test_start — splits must be chronological and non-overlapping"
            )


@dataclass(frozen=True)
class DatasetSplit:
    train: tuple[dict, ...]
    validation: tuple[dict, ...]
    test: tuple[dict, ...]
    dropped_count: int  # rows outside every configured range — never silently included anywhere


def chronological_split(dataset: ResearchDataset, config: SplitConfig) -> DatasetSplit:
    train: list[dict] = []
    validation: list[dict] = []
    test: list[dict] = []
    dropped = 0
    for row in dataset.rows:
        d = row["timestamp"].date()
        if config.train_start <= d <= config.train_end:
            train.append(row)
        elif config.validation_start <= d <= config.validation_end:
            validation.append(row)
        elif config.test_start <= d <= config.test_end:
            test.append(row)
        else:
            dropped += 1
    return DatasetSplit(train=tuple(train), validation=tuple(validation), test=tuple(test), dropped_count=dropped)
