"""Phase 17, Part 11/21I — point-in-time snapshot matrix across multiple
issuers (AAPL, MSFT, NVDA, JPM), using each issuer's REAL 10-K filing
date. T_before/T_filing_date/T_after for every issuer, using real dates,
never invented publication times (Part 11's explicit instruction)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.data.sec_filing_store import SECFactRecord, SECFilingStore
from src.data.sec_snapshot import get_available_facts_for_symbol, latest_known_value

# Real filing dates and real consolidated-revenue values, transcribed from the same probes
# documented in scripts/phase17_step1_ingest_multi_issuer_facts.py.
REAL_10K_FACTS = {
    "AAPL": ("27c07064-a0ab-4224-92ea-2637d8e23c9c", date(2022, 10, 28), "RevenueFromContractWithCustomerExcludingAssessedTax", 394328000000.0, date(2022, 9, 24), date(2021, 9, 26)),
    "MSFT": ("1916c86a-55a4-4de4-b0d7-222bc889eedf", date(2023, 7, 27), "RevenueFromContractWithCustomerExcludingAssessedTax", 211915000000.0, date(2023, 6, 30), date(2022, 7, 1)),
    "NVDA": ("00467f8f-58e8-46a6-b68f-b8eb54a40a59", date(2023, 2, 24), "Revenues", 26974000000.0, date(2023, 1, 29), date(2022, 1, 31)),
    "JPM": ("2461b7c9-0807-4aae-9640-dffd4e5c8069", date(2023, 2, 21), "Revenues", 128695000000.0, date(2022, 12, 31), date(2022, 1, 1)),
}


@pytest.fixture()
def multi_issuer_store(tmp_path) -> SECFilingStore:
    store = SECFilingStore(tmp_path)
    for symbol, (filing_id, filed, concept, value, end, start) in REAL_10K_FACTS.items():
        fact = SECFactRecord(
            issuer_symbol=symbol, filing_id=filing_id, concept=concept, entity_cik="0", unit="iso4217:USD",
            value=value, period_end=end, period_start=start, axises=(), date_filed=filed,
            retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        store.save_facts(symbol, [fact])
    return store


@pytest.mark.parametrize("symbol", ["AAPL", "MSFT", "NVDA", "JPM"])
def test_snapshot_matrix_before_filing_date(multi_issuer_store, symbol):
    _filing_id, filed, _concept, _value, _end, _start = REAL_10K_FACTS[symbol]
    t_before = datetime(filed.year, filed.month, filed.day, tzinfo=timezone.utc)  # 00:00 on the filing date itself
    available = get_available_facts_for_symbol(multi_issuer_store, symbol, as_of=t_before)
    assert available == []


@pytest.mark.parametrize("symbol", ["AAPL", "MSFT", "NVDA", "JPM"])
def test_snapshot_matrix_on_filing_date_end_of_day(multi_issuer_store, symbol):
    _filing_id, filed, _concept, _value, _end, _start = REAL_10K_FACTS[symbol]
    t_filing_eod = datetime(filed.year, filed.month, filed.day, 23, 59, 59, tzinfo=timezone.utc)
    available = get_available_facts_for_symbol(multi_issuer_store, symbol, as_of=t_filing_eod)
    assert available == [], f"{symbol}: fact wrongly available on its own filing date"


@pytest.mark.parametrize("symbol", ["AAPL", "MSFT", "NVDA", "JPM"])
def test_snapshot_matrix_after_filing_date(multi_issuer_store, symbol):
    filing_id, filed, concept, value, end, start = REAL_10K_FACTS[symbol]
    t_after = datetime(filed.year, filed.month, filed.day, tzinfo=timezone.utc) + timedelta(days=1)
    available = get_available_facts_for_symbol(multi_issuer_store, symbol, as_of=t_after)
    assert len(available) == 1
    assert available[0].value == value


@pytest.mark.parametrize("symbol", ["AAPL", "MSFT", "NVDA", "JPM"])
def test_snapshot_matrix_latest_known_revenue_matches_real_value(multi_issuer_store, symbol):
    filing_id, filed, concept, value, end, start = REAL_10K_FACTS[symbol]
    t_after = datetime(filed.year, filed.month, filed.day, tzinfo=timezone.utc) + timedelta(days=30)
    available = get_available_facts_for_symbol(multi_issuer_store, symbol, as_of=t_after)
    result = latest_known_value(available, normalized_concept="revenue")
    assert result is not None
    assert result.value == value


def test_snapshot_matrix_each_issuer_uses_its_own_real_filing_date_not_a_shared_default():
    """Guards against a subtle bug: hardcoding one issuer's filing date
    for all issuers. Every issuer's date_filed in the fixture is
    distinct."""
    dates = {symbol: REAL_10K_FACTS[symbol][1] for symbol in REAL_10K_FACTS}
    assert len(set(dates.values())) == len(dates), f"expected 4 distinct filing dates, got {dates}"
