"""Tests for Phase 6, sections 2-3's holdout-boundary computation and
leakage guard (section 22: "holdout data is not accessible during
parameter selection")."""

from __future__ import annotations

from datetime import date

import pytest

from src.research.holdout import HoldoutLeakageError, HoldoutPeriod, assert_no_holdout_leakage, determine_holdout_split
from src.research.validation import WalkForwardWindow, generate_walk_forward_windows


def test_determine_holdout_split_uses_the_latest_window_test_end():
    windows = generate_walk_forward_windows(start=date(2021, 1, 1), end=date(2024, 1, 1), train_days=200, validation_days=60, test_days=60, step_days=90)
    last_test_end = max(w.test_end for w in windows)
    holdout = determine_holdout_split(windows=windows, full_data_start=date(2021, 1, 1), full_data_end=date(2024, 1, 1))
    assert holdout.development_end == last_test_end
    assert (holdout.holdout_start - last_test_end).days == 1


def test_determine_holdout_split_is_not_hand_picked_it_is_a_pure_function_of_the_windows():
    """Same windows, same data range -> the exact same boundary, every
    time — nothing here depends on strategy performance."""
    windows = generate_walk_forward_windows(start=date(2021, 1, 1), end=date(2024, 1, 1), train_days=200, validation_days=60, test_days=60, step_days=90)
    a = determine_holdout_split(windows=windows, full_data_start=date(2021, 1, 1), full_data_end=date(2024, 1, 1))
    b = determine_holdout_split(windows=windows, full_data_start=date(2021, 1, 1), full_data_end=date(2024, 1, 1))
    assert a == b


def test_determine_holdout_split_requires_at_least_one_window():
    with pytest.raises(ValueError):
        determine_holdout_split(windows=[], full_data_start=date(2021, 1, 1), full_data_end=date(2024, 1, 1))


def test_determine_holdout_split_raises_if_windows_already_reach_the_data_end():
    w = WalkForwardWindow(date(2021, 1, 1), date(2021, 6, 1), date(2021, 6, 2), date(2021, 8, 1), date(2021, 8, 2), date(2022, 1, 1))
    with pytest.raises(ValueError):
        determine_holdout_split(windows=[w], full_data_start=date(2021, 1, 1), full_data_end=date(2022, 1, 1))


def test_holdout_period_rejects_out_of_order_dates():
    with pytest.raises(ValueError):
        HoldoutPeriod(development_start=date(2021, 1, 1), development_end=date(2021, 6, 1), holdout_start=date(2021, 5, 1), holdout_end=date(2021, 8, 1), rationale="test")


def test_assert_no_holdout_leakage_passes_when_period_is_pure_development():
    holdout = HoldoutPeriod(date(2021, 1, 1), date(2023, 12, 31), date(2024, 1, 1), date(2024, 2, 1), rationale="test")
    assert_no_holdout_leakage(period_start=date(2022, 1, 1), period_end=date(2023, 1, 1), holdout=holdout, context="param sweep")  # no raise


def test_assert_no_holdout_leakage_raises_when_period_touches_the_holdout():
    holdout = HoldoutPeriod(date(2021, 1, 1), date(2023, 12, 31), date(2024, 1, 1), date(2024, 2, 1), rationale="test")
    with pytest.raises(HoldoutLeakageError):
        assert_no_holdout_leakage(period_start=date(2023, 12, 1), period_end=date(2024, 1, 15), holdout=holdout, context="param sweep")


def test_assert_no_holdout_leakage_raises_when_period_is_entirely_inside_the_holdout():
    holdout = HoldoutPeriod(date(2021, 1, 1), date(2023, 12, 31), date(2024, 1, 1), date(2024, 2, 1), rationale="test")
    with pytest.raises(HoldoutLeakageError):
        assert_no_holdout_leakage(period_start=date(2024, 1, 5), period_end=date(2024, 1, 10), holdout=holdout, context="walk-forward window")
