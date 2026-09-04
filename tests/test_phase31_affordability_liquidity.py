"""Phase 31, Parts 8 & 9/18 — affordability filter and liquidity/cost reporting."""

from __future__ import annotations

import pytest

from src.options.phase31_affordability_liquidity import (
    affordability_filter_report,
    classify_account_feasibility,
    cost_sensitivity_report,
    liquidity_report,
)


def _row(bid=None, ask=None, volume=None, open_interest=None, spread_pct=None):
    return {"bid": bid, "ask": ask, "volume": volume, "open_interest": open_interest, "spread_pct": spread_pct}


def test_affordability_report_basic_stats():
    rows = [_row(bid=4.0, ask=5.0), _row(bid=8.0, ask=10.0), _row(bid=12.0, ask=15.0)]
    report = affordability_filter_report(rows, account_equity_usd=1000.0)
    assert report.n_priced_rows == 3
    assert report.average_premium_usd == pytest.approx((500 + 1000 + 1500) / 3)
    assert report.min_premium_usd == 500.0
    assert report.max_premium_usd == 1500.0
    assert report.pct_affordable_with_account == pytest.approx(2 / 3)


def test_affordability_report_no_priced_rows():
    rows = [_row(), _row()]
    report = affordability_filter_report(rows)
    assert report.n_priced_rows == 0
    assert report.average_premium_usd is None
    assert report.pct_affordable_with_account is None


def test_spread_cost_uses_real_bid_ask():
    rows = [_row(bid=4.0, ask=5.0)]
    report = affordability_filter_report(rows)
    assert report.average_spread_cost_usd == pytest.approx((5.0 - 4.0) * 100)


def test_account_feasibility_is_a_separate_dimension_from_validity():
    expensive = affordability_filter_report([_row(bid=30.0, ask=35.0)], account_equity_usd=1000.0)
    assert classify_account_feasibility(expensive) == "ACCOUNT_INFEASIBLE_EXPENSIVE_CONTRACTS"
    cheap = affordability_filter_report([_row(bid=1.0, ask=1.2)], account_equity_usd=1000.0)
    assert classify_account_feasibility(cheap) == "ACCOUNT_FEASIBLE"


def test_account_feasibility_unknown_with_no_priced_rows():
    report = affordability_filter_report([_row()])
    assert classify_account_feasibility(report) == "ACCOUNT_FEASIBILITY_UNKNOWN_NO_PRICED_ROWS"


def test_liquidity_report_computes_quote_availability():
    rows = [_row(bid=1.0, ask=1.1, volume=10, open_interest=100, spread_pct=0.05)] * 8 + [_row()] * 2
    report = liquidity_report(rows)
    assert report.pct_quote_available == pytest.approx(0.8)
    assert report.average_spread_pct == pytest.approx(0.05)
    assert report.execution_data_limited is False


def test_liquidity_report_flags_execution_data_limited():
    rows = [_row()] * 9 + [_row(bid=1.0, ask=1.1, spread_pct=0.1)]
    report = liquidity_report(rows)
    assert report.execution_data_limited is True


def test_cost_sensitivity_survives_at_low_multiplier_fails_at_high():
    liquidity = liquidity_report([_row(bid=1.0, ask=1.05, spread_pct=0.02)] * 5)
    results = cost_sensitivity_report(0.05, liquidity, multipliers=(1.0, 2.0, 5.0))
    assert results[0].survives is True  # gross 0.05 - cost 0.02 = 0.03 > 0
    assert results[2].survives is False  # gross 0.05 - cost 0.10 = -0.05 < 0


def test_cost_sensitivity_none_when_no_spread_data():
    liquidity = liquidity_report([_row()] * 5)
    results = cost_sensitivity_report(0.05, liquidity)
    assert all(r.survives is None for r in results)
