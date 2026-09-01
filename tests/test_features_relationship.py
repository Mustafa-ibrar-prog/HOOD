"""Tests for src/features/relationship.py (pairwise correlation/beta/
relative-strength utilities)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from src.data.bar import Bar
from src.features.relationship import align_by_timestamp, relative_strength, rolling_beta, rolling_correlation


def _bars(symbol: str, closes: list[float], offset_days: int = 0):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=offset_days)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol=symbol, timeframe="day", open=c, high=c + 1, low=c - 1, close=c, volume=100)
        for i, c in enumerate(closes)
    ]


def test_perfectly_correlated_series_gives_correlation_near_one():
    base = [100.0 + i * (1 if i % 2 == 0 else -0.5) for i in range(40)]
    closes_a = base
    closes_b = [c * 2 for c in base]  # perfectly linearly related
    values = rolling_correlation(closes_a, closes_b, window=10)
    non_null = [v for v in values if v is not None]
    assert non_null
    assert all(math.isclose(v, 1.0, abs_tol=1e-6) for v in non_null)


def test_rolling_beta_of_identical_series_is_one():
    base = [100.0 + i * (1 if i % 2 == 0 else -0.5) for i in range(40)]
    values = rolling_beta(base, base, window=10)
    non_null = [v for v in values if v is not None]
    assert non_null
    assert all(math.isclose(v, 1.0, abs_tol=1e-9) for v in non_null)


def test_relative_strength_positive_when_a_outperforms():
    closes_a = [100.0 * (1.01**i) for i in range(15)]  # steadily up
    closes_b = [100.0] * 15  # flat
    values = relative_strength(closes_a, closes_b, window=10)
    assert values[10] is not None
    assert values[10] > 0


def test_align_by_timestamp_keeps_only_shared_timestamps():
    bars_a = _bars("AAA", [1, 2, 3, 4], offset_days=0)
    bars_b = _bars("BBB", [10, 20, 30], offset_days=1)  # starts a day later, one fewer bar
    aligned_a, aligned_b = align_by_timestamp(bars_a, bars_b)
    assert len(aligned_a) == len(aligned_b) == 3
    assert [b.timestamp for b in aligned_a] == [b.timestamp for b in aligned_b]
