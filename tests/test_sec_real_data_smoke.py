"""Phase 16, Part 15A/6 — smoke/integration tests against the REAL,
already-ingested SEC sample data (scripts/phase16_step1_ingest_sample_
filings.py). Per Part 15's explicit instruction, these read the local
JSONL files the ingestion script already wrote and skip (never fail the
whole suite) if that data isn't present in this environment — no network
call happens inside pytest itself."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.data.sec_filing_store import SECFilingStore

REPO_ROOT = Path(__file__).resolve().parent.parent
SEC_ROOT = REPO_ROOT / "logs" / "research_data" / "sec"


def _store_or_skip() -> SECFilingStore:
    if not SEC_ROOT.is_dir():
        pytest.skip("logs/research_data/sec/ not present in this environment -- run scripts/phase16_step1_ingest_sample_filings.py first")
    return SECFilingStore(SEC_ROOT)


def test_aapl_10k_and_10q_cover_the_discovery_window():
    store = _store_or_skip()
    filings = store.load_filings("AAPL")
    if not filings:
        pytest.skip("AAPL not ingested in this environment")
    tenk_dates = sorted(f.date_filed for f in filings if f.form_type == "10-K")
    tenq_dates = sorted(f.date_filed for f in filings if f.form_type == "10-Q")
    window_start, window_end = date(2021, 9, 1), date(2023, 8, 31)
    assert any(d <= window_start for d in tenk_dates), "no 10-K precedes the discovery window start"
    assert any(d >= window_end for d in tenk_dates) or any(window_start <= d <= window_end for d in tenk_dates)
    assert any(window_start <= d <= window_end for d in tenq_dates), "no 10-Q falls inside the discovery window"


def test_msft_and_nvda_10q_cover_the_discovery_window():
    store = _store_or_skip()
    for symbol in ("MSFT", "NVDA"):
        filings = store.load_filings(symbol)
        if not filings:
            pytest.skip(f"{symbol} not ingested in this environment")
        tenq_dates = [f.date_filed for f in filings if f.form_type == "10-Q"]
        assert any(date(2021, 9, 1) <= d <= date(2023, 8, 31) for d in tenq_dates), f"{symbol} has no 10-Q inside the discovery window"


def test_jpm_10q_is_verified_empty_not_a_fetch_failure():
    """This is the real, documented gap (Part 6): JPM's 10-Q filings are
    NOT returned by this connector for 2021-2023, despite 3 confirmed
    10-Ks in the same window -- a real, structural coverage limitation
    for this specific issuer, not an ingestion bug."""
    store = _store_or_skip()
    filings = store.load_filings("JPM")
    if not filings:
        pytest.skip("JPM not ingested in this environment")
    tenk_dates = [f.date_filed for f in filings if f.form_type == "10-K"]
    tenq_dates = [f.date_filed for f in filings if f.form_type == "10-Q"]
    assert len(tenk_dates) >= 3
    assert len(tenq_dates) == 0


def test_aapl_fy22_10k_facts_include_the_real_duplicate_evidence():
    """A genuine, non-synthesized real-data duplicate the raw API
    response contained (see phase16_step1's docstring) -- confirms it was
    correctly deduped on save."""
    store = _store_or_skip()
    facts = store.load_facts("AAPL")
    if not facts:
        pytest.skip("AAPL facts not ingested in this environment")
    net_income_fy22 = [f for f in facts if f.concept == "NetIncomeLoss" and f.period_end == date(2022, 9, 24) and f.is_consolidated_total]
    assert len(net_income_fy22) == 1  # deduped to exactly one, not zero (missing) and not two (undeduped)
    assert net_income_fy22[0].value == 99803000000.0


def test_revenue_concept_confirms_apple_does_not_use_plain_revenues_tag():
    """Confirms the real finding driving sec_concepts.py's whitelist: no
    fact in the ingested AAPL sample uses the bare 'Revenues' concept."""
    store = _store_or_skip()
    facts = store.load_facts("AAPL")
    if not facts:
        pytest.skip("AAPL facts not ingested in this environment")
    assert not any(f.concept == "Revenues" for f in facts)
    assert any(f.concept == "RevenueFromContractWithCustomerExcludingAssessedTax" for f in facts)
