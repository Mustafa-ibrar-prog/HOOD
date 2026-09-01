"""Tests for Information Coefficient analysis (Phase 4, section 10)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.research.ic import compute_ic_series, ic_by_period, summarize_ic

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _panel_row(day: int, symbol: str, feature: float, target: float) -> dict:
    return {"timestamp": T0 + timedelta(days=day), "symbol": symbol, "feature_x": feature, "target_y": target}


def test_perfect_rank_agreement_gives_ic_of_one():
    rows = [
        _panel_row(0, "A", 1.0, 0.10), _panel_row(0, "B", 2.0, 0.20), _panel_row(0, "C", 3.0, 0.30),
    ]
    points = compute_ic_series(rows, "feature_x", "target_y", min_universe_size=3)
    assert len(points) == 1
    assert points[0].ic == pytest.approx(1.0)


def test_perfect_rank_inversion_gives_ic_of_negative_one():
    rows = [
        _panel_row(0, "A", 1.0, 0.30), _panel_row(0, "B", 2.0, 0.20), _panel_row(0, "C", 3.0, 0.10),
    ]
    points = compute_ic_series(rows, "feature_x", "target_y", min_universe_size=3)
    assert points[0].ic == pytest.approx(-1.0)


def test_timestamp_below_min_universe_size_is_none():
    rows = [_panel_row(0, "A", 1.0, 0.1), _panel_row(0, "B", 2.0, 0.2)]  # only 2 symbols
    points = compute_ic_series(rows, "feature_x", "target_y", min_universe_size=3)
    assert points[0].ic is None
    assert points[0].sample_count == 2


def test_rows_with_none_values_are_excluded():
    rows = [
        _panel_row(0, "A", 1.0, 0.1), _panel_row(0, "B", 2.0, 0.2), _panel_row(0, "C", 3.0, 0.3),
        {"timestamp": T0, "symbol": "D", "feature_x": None, "target_y": 0.4},
    ]
    points = compute_ic_series(rows, "feature_x", "target_y", min_universe_size=3)
    assert points[0].sample_count == 3  # D excluded


def test_summarize_ic_aggregate_stats():
    rows = []
    for day in range(5):
        rows += [_panel_row(day, "A", 1.0, 0.10), _panel_row(day, "B", 2.0, 0.20), _panel_row(day, "C", 3.0, 0.30)]
    points = compute_ic_series(rows, "feature_x", "target_y", min_universe_size=3)
    summary = summarize_ic(points, feature_name="x", target_name="y")
    assert summary.average_ic == pytest.approx(1.0)
    assert summary.positive_ic_fraction == pytest.approx(1.0)
    assert summary.ic_information_ratio is None  # zero stdev (all ICs identical) -> undefined, not fabricated


def test_summarize_ic_empty_is_safe():
    summary = summarize_ic([], feature_name="x", target_name="y")
    assert summary.average_ic is None


def test_ic_by_period_buckets_by_year():
    rows = []
    for day in [0, 400]:  # spans two different years
        rows += [_panel_row(day, "A", 1.0, 0.10), _panel_row(day, "B", 2.0, 0.20), _panel_row(day, "C", 3.0, 0.30)]
    points = compute_ic_series(rows, "feature_x", "target_y", min_universe_size=3)
    by_year = ic_by_period(points, period="year")
    assert len(by_year) == 2


def test_ic_by_period_rejects_invalid_period():
    with pytest.raises(ValueError):
        ic_by_period([], period="week")
