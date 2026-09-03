"""Phase 20, Part 5/24 — expiration diversity and the
CROSS_SECTIONAL_IC_UNDEFINED discipline."""

from __future__ import annotations

from datetime import date

from src.options.expiration_diversity import (
    CROSS_SECTIONAL_IC_UNDEFINED,
    build_expiration_diversity_report,
    has_cross_sectional_variance,
)


def test_single_expiration_has_no_dte_variance():
    """The exact Phase 19 bug, reproduced structurally: every row shares
    the same dte within a timestamp when there is one expiration."""
    rows = [
        {"timestamp": date(2022, 1, 3), "dte": 74, "symbol": "c1"},
        {"timestamp": date(2022, 1, 3), "dte": 74, "symbol": "c2"},
        {"timestamp": date(2022, 1, 4), "dte": 73, "symbol": "c1"},
        {"timestamp": date(2022, 1, 4), "dte": 73, "symbol": "c2"},
    ]
    assert has_cross_sectional_variance(rows, "dte") is False


def test_multiple_expirations_restores_dte_variance():
    rows = [
        {"timestamp": date(2022, 1, 3), "dte": 74, "symbol": "c1"},  # expiration A
        {"timestamp": date(2022, 1, 3), "dte": 200, "symbol": "c2"},  # expiration B
    ]
    assert has_cross_sectional_variance(rows, "dte") is True


def test_has_cross_sectional_variance_ignores_none_values():
    rows = [{"timestamp": date(2022, 1, 3), "dte": None, "symbol": "c1"}, {"timestamp": date(2022, 1, 3), "dte": None, "symbol": "c2"}]
    assert has_cross_sectional_variance(rows, "dte") is False


def test_sentinel_string_is_exact():
    assert CROSS_SECTIONAL_IC_UNDEFINED == "CROSS_SECTIONAL_IC_UNDEFINED"


def test_build_expiration_diversity_report_single_expiration():
    by_exp = {date(2022, 3, 18): [{"bar_count": 74, "first_bar_date": date(2021, 12, 1)}, {"bar_count": 74, "first_bar_date": date(2021, 12, 1)}]}
    report = build_expiration_diversity_report("AAPL", by_exp)
    assert report.expiration_count == 1
    assert report.has_multiple_expirations is False
    assert report.expiration_spacing_days == ()
    assert report.expirations[0].contract_count == 2
    assert report.expirations[0].usable_observation_count == 148
    assert report.expirations[0].dte_at_first_observation == (date(2022, 3, 18) - date(2021, 12, 1)).days


def test_build_expiration_diversity_report_multiple_expirations():
    by_exp = {
        date(2022, 3, 18): [{"bar_count": 74, "first_bar_date": date(2021, 12, 1)}],
        date(2022, 6, 17): [{"bar_count": 76, "first_bar_date": date(2022, 3, 1)}],
    }
    report = build_expiration_diversity_report("AAPL", by_exp)
    assert report.expiration_count == 2
    assert report.has_multiple_expirations is True
    assert report.expiration_spacing_days == ((date(2022, 6, 17) - date(2022, 3, 18)).days,)


def test_build_expiration_diversity_report_no_first_bar_date():
    by_exp = {date(2022, 3, 18): [{"bar_count": 0, "first_bar_date": None}]}
    report = build_expiration_diversity_report("AAPL", by_exp)
    assert report.expirations[0].dte_at_first_observation is None
