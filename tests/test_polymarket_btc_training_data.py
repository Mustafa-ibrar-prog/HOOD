"""Focused tests for btc_training_data.py -- historical dataset
building and walk-forward splitting for the BTC direction model."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.market.models import PriceBar
from src.polymarket.btc_training_data import (
    build_training_dataset,
    generate_synthetic_bars,
    walk_forward_folds,
)

_T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


_LEAD_IN_MINUTES = 16  # > 15m so has_minimum_data can clear even at the window's own first checkpoint


def _lead_in_bars(*, before: datetime, price: float) -> list[PriceBar]:
    """Flat bars covering the 16 minutes BEFORE `before` -- a standalone
    single-window test fixture has no real history of its own, but
    has_minimum_data requires 15 minutes of bars before ANY checkpoint
    it evaluates, including the window's own first one. Without this,
    EVERY checkpoint in an otherwise-valid single-window fixture would
    fail has_minimum_data for a reason that has nothing to do with
    what each test is actually checking."""
    return [
        PriceBar(
            start_time=before - timedelta(minutes=_LEAD_IN_MINUTES - i), open=price, high=price, low=price,
            close=price, volume=10.0,
        )
        for i in range(_LEAD_IN_MINUTES)
    ]


def _bars_for_one_window(*, start_price: float, end_price: float, minutes: int = 16) -> list[PriceBar]:
    """A real 15-minute window (16 bars: minute 0 through 15) whose
    open price_to_beat is start_price and whose window-end price is
    end_price, with a straight-line path between the two -- PRECEDED
    by enough flat lead-in history for has_minimum_data to clear at
    every checkpoint (see _lead_in_bars())."""
    window = []
    for i in range(minutes):
        price = start_price + (end_price - start_price) * (i / (minutes - 1))
        window.append(PriceBar(start_time=_T0 + timedelta(minutes=i), open=price, high=price, low=price, close=price, volume=10.0))
    return _lead_in_bars(before=_T0, price=start_price) + window


# --- A: labeling -------------------------------------------------------------

def test_a_a_window_that_closes_above_price_to_beat_is_labeled_up():
    bars = _bars_for_one_window(start_price=65_000.0, end_price=65_500.0)
    examples = build_training_dataset(bars, data_source="synthetic", checkpoints_seconds_remaining=(60,))
    assert len(examples) == 1
    assert examples[0].label == 1
    assert examples[0].data_source == "synthetic"


def test_a2_a_window_that_closes_below_price_to_beat_is_labeled_down():
    bars = _bars_for_one_window(start_price=65_000.0, end_price=64_500.0)
    examples = build_training_dataset(bars, data_source="synthetic", checkpoints_seconds_remaining=(60,))
    assert len(examples) == 1
    assert examples[0].label == 0


def test_a3_a_window_that_closes_exactly_at_price_to_beat_is_excluded_a_push():
    bars = _bars_for_one_window(start_price=65_000.0, end_price=65_000.0)
    examples = build_training_dataset(bars, data_source="synthetic", checkpoints_seconds_remaining=(60,))
    assert examples == []


# --- B: no look-ahead --------------------------------------------------------

def test_b_a_checkpoint_feature_vector_never_sees_bars_after_itself():
    # A window that RISES in the first half then FALLS in the second --
    # a checkpoint evaluated mid-window must only see the rise, never
    # the later fall, regardless of the window's eventual label.
    window = []
    prices = [65_000, 65_100, 65_200, 65_300, 65_200, 65_100, 65_000, 64_900, 64_800, 64_700, 64_600, 64_500, 64_400, 64_300, 64_200, 64_100]
    for i, price in enumerate(prices):
        window.append(PriceBar(start_time=_T0 + timedelta(minutes=i), open=price, high=price, low=price, close=price, volume=10.0))
    bars = _lead_in_bars(before=_T0, price=65_000.0) + window
    examples = build_training_dataset(bars, data_source="synthetic", checkpoints_seconds_remaining=(60,))
    assert len(examples) == 1
    # time_remaining=60s means `at` = window_end - 60s = minute 14 -- the
    # feature vector's current_price must be the price AT that point
    # (bars[13].close = 64_300), never a later, lower price from the
    # second half of the window.
    assert examples[0].features.current_price == pytest.approx(64_300.0)


def test_b2_multiple_checkpoints_produce_distinct_feature_vectors():
    bars = _bars_for_one_window(start_price=65_000.0, end_price=66_000.0)
    examples = build_training_dataset(bars, data_source="synthetic", checkpoints_seconds_remaining=(600, 60))
    assert len(examples) == 2
    assert examples[0].features.current_price != examples[1].features.current_price


# --- C: price-to-beat is the window's own opening price ----------------------

def test_c_price_to_beat_is_the_windows_own_opening_price():
    bars = _bars_for_one_window(start_price=65_000.0, end_price=65_500.0)
    examples = build_training_dataset(bars, data_source="synthetic", checkpoints_seconds_remaining=(60,))
    assert examples[0].features.price_to_beat == pytest.approx(65_000.0)


# --- D: non-overlapping, chronological windows -------------------------------

def _shift_bars(bars: list[PriceBar], *, by: timedelta) -> list[PriceBar]:
    return [replace(b, start_time=b.start_time + by) for b in bars]


def test_d_two_consecutive_windows_each_produce_their_own_examples():
    window1 = _bars_for_one_window(start_price=65_000.0, end_price=65_500.0)
    # window1 itself spans minutes -16..15 (lead-in + real); shifting
    # window2 by 32 minutes starts ITS lead-in at minute 16, right
    # after window1's last bar, with no timestamp overlap between them.
    window2_shift = timedelta(minutes=32)
    window2 = _shift_bars(_bars_for_one_window(start_price=65_500.0, end_price=65_000.0), by=window2_shift)
    bars = window1 + window2
    examples = build_training_dataset(bars, data_source="synthetic", checkpoints_seconds_remaining=(60,))
    assert len(examples) == 2
    assert examples[0].window_start == _T0
    assert examples[1].window_start == _T0 + window2_shift
    assert examples[0].label == 1  # window1 rose
    assert examples[1].label == 0  # window2 fell


def test_d2_a_gap_in_the_data_is_skipped_not_stretched():
    window1 = _bars_for_one_window(start_price=65_000.0, end_price=65_500.0)
    # A real gap -- window2 (itself a complete, independently-valid
    # 32-bar block with its own lead-in) starts a full hour later
    # instead of immediately after window1's real portion.
    window2 = _shift_bars(_bars_for_one_window(start_price=65_000.0, end_price=65_500.0), by=timedelta(hours=1))
    bars = window1 + window2
    examples = build_training_dataset(bars, data_source="synthetic", checkpoints_seconds_remaining=(60,))
    # Both windows are still individually valid -- the gap is BETWEEN
    # them, which the sliding scan tolerates (never stretches a window
    # across it, never errors) and each window's own feature lookback
    # correctly stays within its own, ungapped lead-in.
    assert len(examples) == 2


def test_d3_too_few_bars_produces_no_examples():
    bars = _bars_for_one_window(start_price=65_000.0, end_price=65_500.0, minutes=10)  # < 16
    examples = build_training_dataset(bars, data_source="synthetic", checkpoints_seconds_remaining=(60,))
    assert examples == []


# --- E: synthetic data generator is deterministic and clearly labeled -------

def test_e_generate_synthetic_bars_is_deterministic_given_a_seed():
    bars_a = generate_synthetic_bars(num_bars=100, seed=42)
    bars_b = generate_synthetic_bars(num_bars=100, seed=42)
    assert [b.close for b in bars_a] == [b.close for b in bars_b]


def test_e2_different_seeds_produce_different_series():
    bars_a = generate_synthetic_bars(num_bars=100, seed=1)
    bars_b = generate_synthetic_bars(num_bars=100, seed=2)
    assert [b.close for b in bars_a] != [b.close for b in bars_b]


def test_e3_synthetic_examples_are_stamped_with_the_synthetic_data_source():
    bars = generate_synthetic_bars(num_bars=200, seed=7)
    examples = build_training_dataset(bars, data_source="synthetic")
    assert examples  # the generator produces a real, usable series
    assert all(e.data_source == "synthetic" for e in examples)


# --- F: walk-forward folds are chronological, never shuffled ----------------

def test_f_folds_are_chronological_train_always_before_test():
    bars = generate_synthetic_bars(num_bars=2000, seed=3)
    examples = build_training_dataset(bars, data_source="synthetic")
    folds = walk_forward_folds(examples, n_folds=4, min_train_examples=10)
    assert len(folds) >= 1
    for train, test in folds:
        latest_train = max(e.window_start for e in train)
        earliest_test = min(e.window_start for e in test)
        assert latest_train <= earliest_test  # never a test example chronologically before its own training fold


def test_f2_folds_with_too_few_training_examples_are_skipped():
    bars = generate_synthetic_bars(num_bars=200, seed=3)
    examples = build_training_dataset(bars, data_source="synthetic")
    folds = walk_forward_folds(examples, n_folds=10, min_train_examples=10_000)  # impossible threshold
    assert folds == []


def test_f3_zero_examples_produces_no_folds():
    assert walk_forward_folds([], n_folds=4) == []
