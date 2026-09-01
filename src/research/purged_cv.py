"""Phase 7, Part 3: purged / embargoed cross-validation.

Standard K-fold CV assumes samples are independent. Financial labels
built from a forward-looking window (e.g. "return over the next 20 bars")
are NOT independent of nearby samples: a training sample whose label
window [t, t + horizon] overlaps a test fold's time range has effectively
"seen" information that leaks across the train/test boundary, inflating
apparent performance. This is the leakage this module exists to close —
see Lopez de Prado's purged K-fold CV for the general idea; this is a
from-scratch, dependency-free implementation of the same mechanism.

PURGE: remove training samples whose [timestamp, timestamp + horizon)
label window overlaps the test fold's date range at all.
EMBARGO: additionally remove a further `embargo_bars` worth of training
samples immediately AFTER the test fold — even a sample whose own label
window doesn't overlap the test fold can still be correlated with it
through serial dependence in the underlying returns; the embargo is an
extra safety margin, not label-overlap removal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence


@dataclass(frozen=True)
class PurgedCVConfig:
    n_splits: int
    prediction_horizon_bars: int  # how many bars a label at time t looks forward
    purge_window_bars: int  # additional bars purged before AND after a label-overlap boundary (defensive margin)
    embargo_bars: int  # bars purged from training immediately AFTER each test fold
    bar_duration: timedelta = timedelta(days=1)  # converts "bars" to a timedelta for date-only timestamps; override for intraday

    def __post_init__(self) -> None:
        if self.n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        if self.prediction_horizon_bars < 1:
            raise ValueError("prediction_horizon_bars must be >= 1")
        if self.purge_window_bars < 0 or self.embargo_bars < 0:
            raise ValueError("purge_window_bars and embargo_bars must be >= 0")


@dataclass(frozen=True)
class PurgedFold:
    fold_index: int
    test_indices: tuple[int, ...]
    train_indices: tuple[int, ...]
    purged_count: int  # samples removed from what would otherwise be the training set, due to label overlap
    embargoed_count: int  # samples additionally removed due to the embargo window


def generate_purged_folds(timestamps: Sequence[datetime], config: PurgedCVConfig) -> list[PurgedFold]:
    """`timestamps` must be sorted ascending and represent ONE bar/sample
    each — same "one row per (symbol, timestamp)" convention used
    throughout src.research (panel rows). Splits by INDEX into
    `config.n_splits` contiguous test folds (a standard K-fold layout,
    not shuffled — shuffling a time series would itself be a leakage bug),
    then purges + embargoes the training set around each fold."""
    n = len(timestamps)
    if n < config.n_splits:
        raise ValueError(f"cannot make {config.n_splits} folds from {n} samples")
    for i in range(1, n):
        if timestamps[i] < timestamps[i - 1]:
            raise ValueError("timestamps must be sorted ascending")

    horizon_delta = config.prediction_horizon_bars * config.bar_duration
    purge_delta = config.purge_window_bars * config.bar_duration
    embargo_delta = config.embargo_bars * config.bar_duration

    fold_bounds: list[tuple[int, int]] = []
    base_size = n // config.n_splits
    remainder = n % config.n_splits
    start = 0
    for k in range(config.n_splits):
        size = base_size + (1 if k < remainder else 0)
        fold_bounds.append((start, start + size))  # [start, end) index range for this fold's test set
        start += size

    folds: list[PurgedFold] = []
    for fold_index, (test_start_idx, test_end_idx) in enumerate(fold_bounds):
        test_indices = tuple(range(test_start_idx, test_end_idx))
        test_start_ts = timestamps[test_start_idx]
        test_end_ts = timestamps[test_end_idx - 1]

        # A training sample at index i is purged if its label window
        # [ts_i, ts_i + horizon] overlaps [test_start - purge, test_end + purge]
        # (the purge window is a defensive margin applied to BOTH the
        # label-window computation and the test boundary itself).
        purge_lo = test_start_ts - purge_delta
        purge_hi = test_end_ts + horizon_delta + purge_delta
        embargo_hi = test_end_ts + embargo_delta

        train_indices: list[int] = []
        purged = 0
        embargoed = 0
        for i, ts in enumerate(timestamps):
            if test_start_idx <= i < test_end_idx:
                continue  # it's a test sample, not eligible for training regardless
            label_end = ts + horizon_delta
            overlaps_test_window = not (label_end < purge_lo or ts > purge_hi)
            if overlaps_test_window:
                purged += 1
                continue
            if test_end_ts < ts <= embargo_hi:
                embargoed += 1
                continue
            train_indices.append(i)

        folds.append(PurgedFold(fold_index=fold_index, test_indices=test_indices, train_indices=tuple(train_indices), purged_count=purged, embargoed_count=embargoed))

    return folds


def fold_has_leakage(fold: PurgedFold, timestamps: Sequence[datetime], *, prediction_horizon_bars: int, bar_duration: timedelta = timedelta(days=1)) -> bool:
    """A direct, independent check (does NOT reuse generate_purged_folds'
    own purge logic) that no training sample's label window overlaps the
    test fold's date range — used by tests to verify the guarantee
    actually holds, not just that the code claims it does."""
    if not fold.test_indices:
        return False
    test_start = timestamps[fold.test_indices[0]]
    test_end = timestamps[fold.test_indices[-1]]
    horizon_delta = prediction_horizon_bars * bar_duration
    for i in fold.train_indices:
        ts = timestamps[i]
        label_end = ts + horizon_delta
        if not (label_end < test_start or ts > test_end):
            return True
    return False
