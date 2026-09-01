"""Phase 7, Part 3 & 19: purged/embargoed cross-validation tests,
including the required synthetic-data leakage-detection proof."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.research.purged_cv import PurgedCVConfig, fold_has_leakage, generate_purged_folds


def _timestamps(n: int):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(n)]


def test_purged_folds_partition_all_samples_into_test_sets_exactly_once():
    timestamps = _timestamps(100)
    config = PurgedCVConfig(n_splits=5, prediction_horizon_bars=5, purge_window_bars=0, embargo_bars=0)
    folds = generate_purged_folds(timestamps, config)
    all_test = sorted(i for f in folds for i in f.test_indices)
    assert all_test == list(range(100))


def test_purged_folds_never_leak_with_overlapping_labels():
    """The core Part 3/19 requirement: with a horizon large enough to
    create genuine label overlap, EVERY purged fold must show zero
    leakage when independently verified."""
    timestamps = _timestamps(200)
    config = PurgedCVConfig(n_splits=5, prediction_horizon_bars=20, purge_window_bars=2, embargo_bars=5)
    folds = generate_purged_folds(timestamps, config)
    for fold in folds:
        assert fold_has_leakage(fold, timestamps, prediction_horizon_bars=20) is False


def test_naive_kfold_WOULD_leak_on_the_same_data_purged_cv_does_not():
    """Direct proof that purging matters: a naive (non-purged) K-fold on
    the SAME overlapping-label dataset DOES leak in most folds, while the
    purged version does not — demonstrating this isn't a vacuous
    guarantee."""
    timestamps = _timestamps(200)
    horizon = 20

    def naive_kfold(n, k):
        base, rem = divmod(n, k)
        bounds, start = [], 0
        for i in range(k):
            size = base + (1 if i < rem else 0)
            bounds.append((start, start + size))
            start += size
        return bounds

    class _FakeFold:
        def __init__(self, test_indices, train_indices):
            self.test_indices = tuple(test_indices)
            self.train_indices = tuple(train_indices)

    naive_leaks = 0
    for test_start, test_end in naive_kfold(200, 5):
        fake = _FakeFold(range(test_start, test_end), [i for i in range(200) if i < test_start or i >= test_end])
        if fold_has_leakage(fake, timestamps, prediction_horizon_bars=horizon):
            naive_leaks += 1
    assert naive_leaks > 0  # the naive approach DOES leak on this data

    config = PurgedCVConfig(n_splits=5, prediction_horizon_bars=horizon, purge_window_bars=2, embargo_bars=5)
    purged_folds = generate_purged_folds(timestamps, config)
    purged_leaks = sum(1 for f in purged_folds if fold_has_leakage(f, timestamps, prediction_horizon_bars=horizon))
    assert purged_leaks == 0  # purged CV eliminates it entirely


def test_embargo_removes_additional_training_samples_right_after_the_test_fold():
    timestamps = _timestamps(200)
    config_no_embargo = PurgedCVConfig(n_splits=5, prediction_horizon_bars=1, purge_window_bars=0, embargo_bars=0)
    config_with_embargo = PurgedCVConfig(n_splits=5, prediction_horizon_bars=1, purge_window_bars=0, embargo_bars=10)
    folds_no_embargo = generate_purged_folds(timestamps, config_no_embargo)
    folds_with_embargo = generate_purged_folds(timestamps, config_with_embargo)
    assert folds_with_embargo[0].embargoed_count > folds_no_embargo[0].embargoed_count


def test_rejects_unsorted_timestamps():
    timestamps = _timestamps(50)
    timestamps[10], timestamps[11] = timestamps[11], timestamps[10]
    config = PurgedCVConfig(n_splits=5, prediction_horizon_bars=1, purge_window_bars=0, embargo_bars=0)
    with pytest.raises(ValueError):
        generate_purged_folds(timestamps, config)


def test_config_rejects_invalid_values():
    with pytest.raises(ValueError):
        PurgedCVConfig(n_splits=1, prediction_horizon_bars=5, purge_window_bars=0, embargo_bars=0)
    with pytest.raises(ValueError):
        PurgedCVConfig(n_splits=5, prediction_horizon_bars=0, purge_window_bars=0, embargo_bars=0)
    with pytest.raises(ValueError):
        PurgedCVConfig(n_splits=5, prediction_horizon_bars=5, purge_window_bars=-1, embargo_bars=0)


def test_too_few_samples_for_n_splits_raises():
    timestamps = _timestamps(3)
    config = PurgedCVConfig(n_splits=5, prediction_horizon_bars=1, purge_window_bars=0, embargo_bars=0)
    with pytest.raises(ValueError):
        generate_purged_folds(timestamps, config)
