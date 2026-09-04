"""Phase 32, Parts 12, 13 & 14/21 — economic significance, extended
affordability, and tradeability classification."""

from __future__ import annotations

from src.options.phase31_classification import DiscoveryClassification
from src.options.phase32_affordability import (
    TradeabilityClassification,
    build_bucket_affordability_report,
    classify_tradeability,
)


def _contract(option_id, underlying, ask):
    return {"option_id": option_id, "underlying_symbol": underlying, "ask": ask}


def test_affordability_report_computes_percentiles():
    rows = [_contract(f"c{i}", "AAPL", float(i + 1)) for i in range(100)]  # ask 1..100 -> premium 100..10000
    report = build_bucket_affordability_report(rows, account_equity_usd=1000.0)
    assert report.n_priced == 100
    assert report.median_premium_usd == 5100.0  # ask=51 -> 5100
    assert report.p25_premium_usd < report.median_premium_usd < report.p75_premium_usd


def test_affordability_report_cheapest_contracts_sorted():
    rows = [_contract("c1", "AAPL", 5.0), _contract("c2", "AAPL", 1.0), _contract("c3", "AAPL", 3.0)]
    report = build_bucket_affordability_report(rows, n_cheapest=2)
    assert [c.option_id for c in report.cheapest_contracts] == ["c2", "c3"]
    assert report.capital_concentration_cheapest_usd == (1.0 * 100) / 1000.0


def test_affordability_report_no_priced_rows():
    rows = [{"option_id": "c1", "underlying_symbol": "AAPL", "ask": None}]
    report = build_bucket_affordability_report(rows)
    assert report.n_priced == 0
    assert report.median_premium_usd is None
    assert report.cheapest_contracts == ()


def test_pct_affordable_and_over_account():
    rows = [_contract("cheap", "AAPL", 1.0), _contract("expensive", "AAPL", 50.0)]  # 100 vs 5000
    report = build_bucket_affordability_report(rows, account_equity_usd=1000.0)
    assert report.pct_affordable == 0.5
    assert report.pct_requiring_over_account == 0.5


def test_tradeability_data_limited_when_no_priced_rows():
    report = build_bucket_affordability_report([])
    result = classify_tradeability(report, DiscoveryClassification.DISCOVERY_SUPPORTED)
    assert result == TradeabilityClassification.DATA_LIMITED


def test_tradeability_not_applicable_when_no_statistical_signal():
    rows = [_contract("c1", "AAPL", 1.0)]
    report = build_bucket_affordability_report(rows)
    result = classify_tradeability(report, DiscoveryClassification.INCONCLUSIVE)
    assert result == TradeabilityClassification.NOT_APPLICABLE_NO_STATISTICAL_SIGNAL


def test_tradeability_tradeable_when_affordable_and_supported():
    rows = [_contract(f"c{i}", "AAPL", 1.0) for i in range(10)]  # $100 premium, cheap
    report = build_bucket_affordability_report(rows, account_equity_usd=1000.0)
    result = classify_tradeability(report, DiscoveryClassification.DISCOVERY_SUPPORTED)
    assert result == TradeabilityClassification.TRADEABLE


def test_tradeability_fragile_when_mostly_unaffordable_but_some_qualify():
    rows = [_contract(f"c{i}", "AAPL", 50.0) for i in range(9)] + [_contract("cheap", "AAPL", 1.0)]  # 9 expensive, 1 cheap
    report = build_bucket_affordability_report(rows, account_equity_usd=1000.0)
    result = classify_tradeability(report, DiscoveryClassification.PROMISING)
    assert result == TradeabilityClassification.TRADEABLE_SIGNAL_FRAGILE


def test_tradeability_not_tradeable_when_nothing_affordable():
    rows = [_contract(f"c{i}", "AAPL", 50.0) for i in range(10)]  # all $5000, none affordable
    report = build_bucket_affordability_report(rows, account_equity_usd=1000.0)
    result = classify_tradeability(report, DiscoveryClassification.DISCOVERY_SUPPORTED)
    assert result == TradeabilityClassification.NOT_TRADEABLE_TOO_EXPENSIVE
