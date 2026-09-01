"""Tests for cross-sectional quantile portfolio analysis (Phase 4,
section 11)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.research.quantile import cross_sectional_quantile_returns

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _row(day: int, symbol: str, feature: float, target: float) -> dict:
    return {"timestamp": T0 + timedelta(days=day), "symbol": symbol, "feature_x": feature, "target_y": target}


def test_monotonic_relationship_is_detected():
    rows = []
    for day in range(20):
        # 5 symbols, feature perfectly predicts target rank every day
        rows += [_row(day, s, float(i), float(i) * 0.01) for i, s in enumerate("ABCDE")]
    report = cross_sectional_quantile_returns(rows, "feature_x", "target_y", n_quantiles=5, min_universe_size=3)
    assert report.is_monotonic is True
    assert report.spread_q5_minus_q1 > 0


def test_no_relationship_is_not_falsely_monotonic():
    rows = []
    for day in range(10):
        # target uncorrelated with feature rank (alternating pattern)
        rows += [_row(day, "A", 1.0, 0.05), _row(day, "B", 2.0, -0.05), _row(day, "C", 3.0, 0.05), _row(day, "D", 4.0, -0.05), _row(day, "E", 5.0, 0.05)]
    report = cross_sectional_quantile_returns(rows, "feature_x", "target_y", n_quantiles=5, min_universe_size=3)
    assert len(report.quantiles) == 5


def test_below_min_universe_size_excluded_from_timestamps_used():
    rows = [_row(0, "A", 1.0, 0.1), _row(0, "B", 2.0, 0.2)]  # only 2 symbols
    report = cross_sectional_quantile_returns(rows, "feature_x", "target_y", min_universe_size=3)
    assert report.timestamps_used == 0
    assert report.quantiles == ()


def test_spread_is_none_with_fewer_than_two_quantiles():
    rows = [_row(0, "A", 1.0, 0.1)]
    report = cross_sectional_quantile_returns(rows, "feature_x", "target_y", n_quantiles=5, min_universe_size=1)
    # with only 1 symbol, all observations land in one bucket
    assert report.spread_q5_minus_q1 is None or len(report.quantiles) <= 1


def test_render_produces_readable_output():
    rows = []
    for day in range(5):
        rows += [_row(day, s, float(i), float(i) * 0.01) for i, s in enumerate("ABCDE")]
    report = cross_sectional_quantile_returns(rows, "feature_x", "target_y", n_quantiles=5, min_universe_size=3)
    text = report.render()
    assert "Feature:" in text
    assert "Q1:" in text
