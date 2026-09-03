"""Phase 21, Part 10 — winsorization, top/bottom-percent removal, top-N
observation ranking, and outlier attribution."""

from __future__ import annotations

import pytest

from src.options.outlier_treatment import (
    OutlierAttribution,
    TopObservation,
    compute_outlier_attribution,
    remove_top_percent,
    top_observations,
    winsorize,
)


def test_winsorize_empty_returns_empty():
    assert winsorize([], fraction=0.01) == []


def test_winsorize_rejects_fraction_out_of_range():
    with pytest.raises(ValueError):
        winsorize([1.0, 2.0], fraction=0.5)
    with pytest.raises(ValueError):
        winsorize([1.0, 2.0], fraction=-0.01)


def test_winsorize_caps_extremes_without_changing_length():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 100.0]  # one extreme outlier
    result = winsorize(values, fraction=0.1)
    assert len(result) == len(values)
    assert max(result) < 100.0  # the extreme value was capped
    assert max(result) == 9.0  # capped to the 90th percentile boundary


def test_winsorize_does_not_remove_middle_values():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = winsorize(values, fraction=0.1)
    # middle values unaffected since 0.1 * 5 rounds down to 0 clipped index changes
    assert result[2] == 3.0


def test_remove_top_percent_positive_side_removes_largest_values():
    values = [1.0, 2.0, 3.0, -100.0, 1000.0]  # 1000.0 is the single largest positive
    result = remove_top_percent(values, fraction=0.2, side="positive")
    assert 1000.0 not in result
    assert len(result) == len(values) - 1


def test_remove_top_percent_negative_side_removes_most_negative_values():
    values = [1.0, 2.0, 3.0, -100.0, 1000.0]
    result = remove_top_percent(values, fraction=0.2, side="negative")
    assert -100.0 not in result
    assert len(result) == len(values) - 1


def test_remove_top_percent_zero_fraction_removes_nothing():
    values = [1.0, 2.0, 3.0]
    assert remove_top_percent(values, fraction=0.0, side="positive") == values


def test_remove_top_percent_rejects_bad_side():
    with pytest.raises(ValueError):
        remove_top_percent([1.0], fraction=0.1, side="sideways")


def test_remove_top_percent_empty_returns_empty():
    assert remove_top_percent([], fraction=0.1, side="positive") == []


def test_top_observations_absolute_ranks_by_magnitude():
    values = [1.0, -50.0, 3.0, 40.0, -2.0]
    top = top_observations(values, n=2, by="absolute")
    assert isinstance(top[0], TopObservation)
    assert [o.value for o in top] == [-50.0, 40.0]
    assert [o.index for o in top] == [1, 3]


def test_top_observations_positive_ranks_high_to_low():
    values = [1.0, -50.0, 3.0, 40.0, -2.0]
    top = top_observations(values, n=2, by="positive")
    assert [o.value for o in top] == [40.0, 3.0]


def test_top_observations_negative_ranks_most_negative_first():
    values = [1.0, -50.0, 3.0, 40.0, -2.0]
    top = top_observations(values, n=2, by="negative")
    assert [o.value for o in top] == [-50.0, -2.0]


def test_top_observations_rejects_bad_by():
    with pytest.raises(ValueError):
        top_observations([1.0], n=1, by="sideways")


def test_top_observations_n_larger_than_values_returns_all():
    values = [1.0, 2.0]
    assert len(top_observations(values, n=10)) == 2


def test_compute_outlier_attribution_empty():
    attribution = compute_outlier_attribution([])
    assert isinstance(attribution, OutlierAttribution)
    assert attribution.total_sum == 0.0
    assert attribution.top_1pct_share is None  # total_sum == 0 -> undefined share


def test_compute_outlier_attribution_single_extreme_dominates():
    # 99 small values + 1 huge value: the huge value should dominate the top-1% share
    values = [0.01] * 99 + [1000.0]
    attribution = compute_outlier_attribution(values)
    assert attribution.top_1pct_share is not None
    assert attribution.top_1pct_share > 0.9  # nearly all of the total sum


def test_compute_outlier_attribution_shares_are_monotonic():
    values = [float(i) for i in range(1, 101)]
    attribution = compute_outlier_attribution(values)
    assert attribution.top_1pct_share <= attribution.top_5pct_share <= attribution.top_10pct_share


def test_compute_outlier_attribution_zero_total_sum_gives_none_shares():
    values = [10.0, -10.0]
    attribution = compute_outlier_attribution(values)
    assert attribution.total_sum == 0.0
    assert attribution.top_1pct_share is None
    assert attribution.top_5pct_share is None
    assert attribution.top_10pct_share is None
