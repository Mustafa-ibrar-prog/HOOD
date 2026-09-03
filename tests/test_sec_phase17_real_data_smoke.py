"""Phase 17, Part 15/21A — smoke/integration tests against the REAL,
already-ingested multi-issuer SEC data (scripts/phase17_step1_ingest_
multi_issuer_facts.py). Skips (never fails the whole suite) if that data
isn't present in this environment -- no network call happens inside
pytest itself (Part 15's explicit instruction)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.data.sec_filing_store import SECFilingStore

REPO_ROOT = Path(__file__).resolve().parent.parent
SEC_ROOT = REPO_ROOT / "logs" / "research_data" / "sec"


def _store_or_skip() -> SECFilingStore:
    if not SEC_ROOT.is_dir():
        pytest.skip("logs/research_data/sec/ not present -- run scripts/phase17_step1_ingest_multi_issuer_facts.py first")
    return SECFilingStore(SEC_ROOT)


def test_msft_revenue_tagged_same_as_aapl():
    store = _store_or_skip()
    facts = store.load_facts("MSFT")
    if not facts:
        pytest.skip("MSFT not ingested in this environment")
    assert any(f.concept == "RevenueFromContractWithCustomerExcludingAssessedTax" and f.is_consolidated_total for f in facts)
    assert not any(f.concept == "Revenues" for f in facts)


def test_nvda_and_jpm_revenue_tagged_differently_from_aapl_msft():
    store = _store_or_skip()
    for symbol in ("NVDA", "JPM"):
        facts = store.load_facts(symbol)
        if not facts:
            pytest.skip(f"{symbol} not ingested in this environment")
        assert any(f.concept == "Revenues" and f.is_consolidated_total for f in facts)
        assert not any(f.concept == "RevenueFromContractWithCustomerExcludingAssessedTax" for f in facts)


def test_jpm_has_no_operating_income_or_cash_and_equivalents_facts():
    store = _store_or_skip()
    facts = store.load_facts("JPM")
    if not facts:
        pytest.skip("JPM not ingested in this environment")
    assert not any(f.concept == "OperatingIncomeLoss" for f in facts)
    assert not any(f.concept == "CashAndCashEquivalentsAtCarryingValue" for f in facts)
    # JPM's real, documented alternative IS present
    assert any(f.concept == "CashAndDueFromBanks" and f.is_consolidated_total for f in facts)


def test_aapl_q3_fy2023_10q_has_both_quarterly_and_ytd_revenue():
    store = _store_or_skip()
    facts = store.load_facts("AAPL")
    if not facts:
        pytest.skip("AAPL not ingested in this environment")
    revenue_facts = [f for f in facts if f.concept == "RevenueFromContractWithCustomerExcludingAssessedTax" and f.is_consolidated_total and f.period_end == date(2023, 7, 1)]
    spans = {(f.period_end - f.period_start).days for f in revenue_facts if f.period_start}
    assert any(85 <= d <= 95 for d in spans), f"no ~90-day quarterly span found among {spans}"
    assert any(270 <= d <= 285 for d in spans), f"no ~279-day YTD span found among {spans}"


def test_aapl_capex_present_and_positive():
    store = _store_or_skip()
    facts = store.load_facts("AAPL")
    if not facts:
        pytest.skip("AAPL not ingested in this environment")
    capex_facts = [f for f in facts if f.concept == "PaymentsToAcquirePropertyPlantAndEquipment" and f.is_consolidated_total]
    assert len(capex_facts) == 3
    assert all(f.value > 0 for f in capex_facts)


def test_no_amendments_ingested_for_any_of_the_four_issuers():
    """Confirms the real Part 10 finding: zero 10-K/A or 10-Q/A filings
    were found for AAPL/MSFT/NVDA/JPM in the probed window."""
    store = _store_or_skip()
    for symbol in ("AAPL", "MSFT", "NVDA", "JPM"):
        filings = store.load_filings(symbol)
        if not filings:
            continue
        assert not any(f.is_amendment for f in filings), f"{symbol} unexpectedly has an ingested amendment"
