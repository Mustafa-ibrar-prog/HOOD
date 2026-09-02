"""Phase 10, Parts 12-14 & 28: state-conditional distributional-stats
tests (src/research/state_conditional_stats.py), using hand-computed
examples.
"""

from __future__ import annotations

from src.research.state_conditional_stats import bucket_stats_by_state


def _rows(state_values: dict[str, list[float]]) -> list[dict]:
    rows = []
    for state, values in state_values.items():
        for v in values:
            rows.append({"state": state, "target": v})
    return rows


def test_mean_median_stdev_hand_computed():
    rows = _rows({"HIGH": [1.0, 2.0, 3.0, 4.0, 5.0]})
    result = bucket_stats_by_state(rows, "state", "target", min_count=3)
    stats = result["HIGH"]
    assert stats.sample_count == 5
    assert stats.mean_value == 3.0
    assert stats.median_value == 3.0
    assert stats.win_rate == 1.0  # all positive


def test_win_rate_and_downside_deviation():
    rows = _rows({"LOW": [1.0, -1.0, 2.0, -2.0, 0.5, -0.5]})
    result = bucket_stats_by_state(rows, "state", "target", min_count=3)
    stats = result["LOW"]
    assert abs(stats.win_rate - 3 / 6) < 1e-9
    assert stats.downside_deviation is not None  # 3 negative values -> defined stdev


def test_below_min_count_returns_none_stats_but_keeps_sample_count():
    rows = _rows({"RARE": [1.0, 2.0]})
    result = bucket_stats_by_state(rows, "state", "target", min_count=5)
    stats = result["RARE"]
    assert stats.sample_count == 2
    assert stats.mean_value is None


def test_none_values_are_dropped_not_counted():
    rows = [{"state": "HIGH", "target": 1.0}, {"state": "HIGH", "target": None}, {"state": None, "target": 2.0}]
    result = bucket_stats_by_state(rows, "state", "target", min_count=1)
    assert result["HIGH"].sample_count == 1
    assert "None" not in result


def test_mean_absolute_value_and_sharpe_like_hand_computed():
    rows = _rows({"HIGH": [2.0, -2.0, 2.0, -2.0]})
    result = bucket_stats_by_state(rows, "state", "target", min_count=3)
    stats = result["HIGH"]
    assert stats.mean_absolute_value == 2.0
    assert stats.mean_value == 0.0
    assert stats.sharpe_like == 0.0  # mean 0 / nonzero stdev
