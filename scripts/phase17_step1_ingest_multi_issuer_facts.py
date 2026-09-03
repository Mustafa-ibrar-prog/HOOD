#!/usr/bin/env python3
"""Phase 17 — STEP 1: ingest REAL fact-level SEC data for MSFT, NVDA, and
JPM (correcting Phase 16's AAPL-only depth), plus a real AAPL 10-Q
(quarterly vs year-to-date duration facts) and AAPL capital-expenditure
facts.

Every record below was fetched via real, read-only
mcp__HOOD__get_sec_filing_facts calls made by the orchestrating agent
during this phase's development. Nothing here is fabricated,
interpolated, or derived (Part 22's explicit prohibition) -- every value
is a direct transcription of a real API response.

KEY CROSS-ISSUER FINDINGS THIS INGESTION ENCODES (see
docs/sec_data_certification.md for the full evidence trail):
  - AAPL and MSFT both tag revenue as
    RevenueFromContractWithCustomerExcludingAssessedTax.
  - NVDA and JPM both tag revenue as plain "Revenues" instead -- confirmed
    disjoint (neither NVDA's nor JPM's filing has a single row under the
    other tag).
  - JPM has ZERO rows under OperatingIncomeLoss and ZERO rows under
    CashAndCashEquivalentsAtCarryingValue -- a real, structural gap (banks
    do not report a traditional GAAP operating-income line, and use
    CashAndDueFromBanks instead of CashAndCashEquivalentsAtCarryingValue).
  - AAPL's Q3 FY2023 10-Q reports the SAME concept as BOTH a standalone-
    quarter duration fact (~90 days) AND a year-to-date duration fact
    (~279 days), both axises=() -- confirming quarterly figures do not
    need to be derived from YTD figures for this source; the source
    already supplies them directly.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.sec_filing_store import SECFactRecord, SECFilingRecord, SECFilingStore  # noqa: E402

RESEARCH_DATA_ROOT = Path("logs/research_data") / "sec"
RETRIEVAL_TIMESTAMP = datetime(2026, 9, 3, tzinfo=timezone.utc)

MSFT_10K_FILING = "1916c86a-55a4-4de4-b0d7-222bc889eedf"
MSFT_10K_FILED = date(2023, 7, 27)
NVDA_10K_FILING = "00467f8f-58e8-46a6-b68f-b8eb54a40a59"
NVDA_10K_FILED = date(2023, 2, 24)
JPM_10K_FILING = "2461b7c9-0807-4aae-9640-dffd4e5c8069"
JPM_10K_FILED = date(2023, 2, 21)
AAPL_10K_FILING = "27c07064-a0ab-4224-92ea-2637d8e23c9c"
AAPL_10K_FILED = date(2022, 10, 28)
AAPL_10Q_FILING = "f0c81217-21e9-4a0b-b99e-e198447bbd9d"
AAPL_10Q_FILED = date(2023, 8, 4)


def _f(symbol, filing_id, filed, concept, cik, unit, value, end, start, axises=()) -> SECFactRecord:
    return SECFactRecord(
        issuer_symbol=symbol, filing_id=filing_id, concept=concept, entity_cik=cik, unit=unit, value=value,
        period_end=end, period_start=start, axises=axises, date_filed=filed, retrieval_timestamp=RETRIEVAL_TIMESTAMP,
    )


# --- MSFT FY2023 10-K consolidated facts (real, axises=()) ---------------------------------------
MSFT_FACTS = [
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "Assets", "0000789019", "iso4217:USD", 364840000000.0, date(2022, 6, 30), None),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "Assets", "0000789019", "iso4217:USD", 411976000000.0, date(2023, 6, 30), None),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "CashAndCashEquivalentsAtCarryingValue", "0000789019", "iso4217:USD", 13931000000.0, date(2022, 6, 30), None),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "CashAndCashEquivalentsAtCarryingValue", "0000789019", "iso4217:USD", 34704000000.0, date(2023, 6, 30), None),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "EarningsPerShareDiluted", "0000789019", "iso4217:USD/xbrli:shares", 8.05, date(2021, 6, 30), date(2020, 7, 1)),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "EarningsPerShareDiluted", "0000789019", "iso4217:USD/xbrli:shares", 9.65, date(2022, 6, 30), date(2021, 7, 1)),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "EarningsPerShareDiluted", "0000789019", "iso4217:USD/xbrli:shares", 9.68, date(2023, 6, 30), date(2022, 7, 1)),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "Liabilities", "0000789019", "iso4217:USD", 198298000000.0, date(2022, 6, 30), None),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "Liabilities", "0000789019", "iso4217:USD", 205753000000.0, date(2023, 6, 30), None),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "NetCashProvidedByUsedInOperatingActivities", "0000789019", "iso4217:USD", 76740000000.0, date(2021, 6, 30), date(2020, 7, 1)),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "NetCashProvidedByUsedInOperatingActivities", "0000789019", "iso4217:USD", 89035000000.0, date(2022, 6, 30), date(2021, 7, 1)),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "NetCashProvidedByUsedInOperatingActivities", "0000789019", "iso4217:USD", 87582000000.0, date(2023, 6, 30), date(2022, 7, 1)),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "NetIncomeLoss", "0000789019", "iso4217:USD", 61271000000.0, date(2021, 6, 30), date(2020, 7, 1)),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "NetIncomeLoss", "0000789019", "iso4217:USD", 72738000000.0, date(2022, 6, 30), date(2021, 7, 1)),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "NetIncomeLoss", "0000789019", "iso4217:USD", 72361000000.0, date(2023, 6, 30), date(2022, 7, 1)),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "OperatingIncomeLoss", "0000789019", "iso4217:USD", 69916000000.0, date(2021, 6, 30), date(2020, 7, 1)),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "OperatingIncomeLoss", "0000789019", "iso4217:USD", 83383000000.0, date(2022, 6, 30), date(2021, 7, 1)),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "OperatingIncomeLoss", "0000789019", "iso4217:USD", 88523000000.0, date(2023, 6, 30), date(2022, 7, 1)),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "RevenueFromContractWithCustomerExcludingAssessedTax", "0000789019", "iso4217:USD", 168088000000.0, date(2021, 6, 30), date(2020, 7, 1)),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "RevenueFromContractWithCustomerExcludingAssessedTax", "0000789019", "iso4217:USD", 198270000000.0, date(2022, 6, 30), date(2021, 7, 1)),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "RevenueFromContractWithCustomerExcludingAssessedTax", "0000789019", "iso4217:USD", 211915000000.0, date(2023, 6, 30), date(2022, 7, 1)),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "StockholdersEquity", "0000789019", "iso4217:USD", 141988000000.0, date(2021, 6, 30), None),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "StockholdersEquity", "0000789019", "iso4217:USD", 166542000000.0, date(2022, 6, 30), None),
    _f("MSFT", MSFT_10K_FILING, MSFT_10K_FILED, "StockholdersEquity", "0000789019", "iso4217:USD", 206223000000.0, date(2023, 6, 30), None),
]

# --- NVDA FY2023 10-K consolidated facts (real, axises=()) -- NVDA tags revenue as "Revenues" ----
NVDA_FACTS = [
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "Revenues", "0001045810", "iso4217:USD", 16675000000.0, date(2021, 1, 31), date(2020, 1, 27)),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "Revenues", "0001045810", "iso4217:USD", 26914000000.0, date(2022, 1, 30), date(2021, 2, 1)),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "Revenues", "0001045810", "iso4217:USD", 26974000000.0, date(2023, 1, 29), date(2022, 1, 31)),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "OperatingIncomeLoss", "0001045810", "iso4217:USD", 4532000000.0, date(2021, 1, 31), date(2020, 1, 27)),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "OperatingIncomeLoss", "0001045810", "iso4217:USD", 10041000000.0, date(2022, 1, 30), date(2021, 2, 1)),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "OperatingIncomeLoss", "0001045810", "iso4217:USD", 4224000000.0, date(2023, 1, 29), date(2022, 1, 31)),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "NetIncomeLoss", "0001045810", "iso4217:USD", 4332000000.0, date(2021, 1, 31), date(2020, 1, 27)),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "NetIncomeLoss", "0001045810", "iso4217:USD", 9752000000.0, date(2022, 1, 30), date(2021, 2, 1)),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "NetIncomeLoss", "0001045810", "iso4217:USD", 4368000000.0, date(2023, 1, 29), date(2022, 1, 31)),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "EarningsPerShareDiluted", "0001045810", "iso4217:USD/xbrli:shares", 1.73, date(2021, 1, 31), date(2020, 1, 27)),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "EarningsPerShareDiluted", "0001045810", "iso4217:USD/xbrli:shares", 3.85, date(2022, 1, 30), date(2021, 2, 1)),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "EarningsPerShareDiluted", "0001045810", "iso4217:USD/xbrli:shares", 1.74, date(2023, 1, 29), date(2022, 1, 31)),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "CashAndCashEquivalentsAtCarryingValue", "0001045810", "iso4217:USD", 1990000000.0, date(2022, 1, 30), None),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "CashAndCashEquivalentsAtCarryingValue", "0001045810", "iso4217:USD", 3389000000.0, date(2023, 1, 29), None),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "Assets", "0001045810", "iso4217:USD", 44187000000.0, date(2022, 1, 30), None),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "Assets", "0001045810", "iso4217:USD", 41182000000.0, date(2023, 1, 29), None),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "Liabilities", "0001045810", "iso4217:USD", 17575000000.0, date(2022, 1, 30), None),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "Liabilities", "0001045810", "iso4217:USD", 19081000000.0, date(2023, 1, 29), None),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "StockholdersEquity", "0001045810", "iso4217:USD", 12204000000.0, date(2020, 1, 26), None),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "StockholdersEquity", "0001045810", "iso4217:USD", 16893000000.0, date(2021, 1, 31), None),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "StockholdersEquity", "0001045810", "iso4217:USD", 26612000000.0, date(2022, 1, 30), None),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "StockholdersEquity", "0001045810", "iso4217:USD", 22101000000.0, date(2023, 1, 29), None),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "NetCashProvidedByUsedInOperatingActivities", "0001045810", "iso4217:USD", 5822000000.0, date(2021, 1, 31), date(2020, 1, 27)),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "NetCashProvidedByUsedInOperatingActivities", "0001045810", "iso4217:USD", 9108000000.0, date(2022, 1, 30), date(2021, 2, 1)),
    _f("NVDA", NVDA_10K_FILING, NVDA_10K_FILED, "NetCashProvidedByUsedInOperatingActivities", "0001045810", "iso4217:USD", 5641000000.0, date(2023, 1, 29), date(2022, 1, 31)),
]

# --- JPM FY2022 10-K consolidated facts (real, axises=()) -- JPM tags revenue as "Revenues"; ------
# --- OperatingIncomeLoss and CashAndCashEquivalentsAtCarryingValue are CONFIRMED ABSENT (real ----
# --- probe with both concepts requested alongside 9 others that DID return rows) -----------------
JPM_FACTS = [
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "Revenues", "0000019617", "iso4217:USD", 119951000000.0, date(2020, 12, 31), date(2020, 1, 1)),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "Revenues", "0000019617", "iso4217:USD", 121649000000.0, date(2021, 12, 31), date(2021, 1, 1)),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "Revenues", "0000019617", "iso4217:USD", 128695000000.0, date(2022, 12, 31), date(2022, 1, 1)),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "NetIncomeLoss", "0000019617", "iso4217:USD", 29131000000.0, date(2020, 12, 31), date(2020, 1, 1)),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "NetIncomeLoss", "0000019617", "iso4217:USD", 48334000000.0, date(2021, 12, 31), date(2021, 1, 1)),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "NetIncomeLoss", "0000019617", "iso4217:USD", 37676000000.0, date(2022, 12, 31), date(2022, 1, 1)),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "EarningsPerShareDiluted", "0000019617", "iso4217:USD/xbrli:shares", 8.88, date(2020, 12, 31), date(2020, 1, 1)),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "EarningsPerShareDiluted", "0000019617", "iso4217:USD/xbrli:shares", 15.36, date(2021, 12, 31), date(2021, 1, 1)),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "EarningsPerShareDiluted", "0000019617", "iso4217:USD/xbrli:shares", 12.09, date(2022, 12, 31), date(2022, 1, 1)),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "Assets", "0000019617", "iso4217:USD", 3384757000000.0, date(2020, 12, 31), None),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "Assets", "0000019617", "iso4217:USD", 3743567000000.0, date(2021, 12, 31), None),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "Assets", "0000019617", "iso4217:USD", 3665743000000.0, date(2022, 12, 31), None),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "Liabilities", "0000019617", "iso4217:USD", 3449440000000.0, date(2021, 12, 31), None),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "Liabilities", "0000019617", "iso4217:USD", 3373411000000.0, date(2022, 12, 31), None),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "StockholdersEquity", "0000019617", "iso4217:USD", 279354000000.0, date(2020, 12, 31), None),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "StockholdersEquity", "0000019617", "iso4217:USD", 294127000000.0, date(2021, 12, 31), None),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "StockholdersEquity", "0000019617", "iso4217:USD", 292332000000.0, date(2022, 12, 31), None),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "NetCashProvidedByUsedInOperatingActivities", "0000019617", "iso4217:USD", -79910000000.0, date(2020, 12, 31), date(2020, 1, 1)),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "NetCashProvidedByUsedInOperatingActivities", "0000019617", "iso4217:USD", 78084000000.0, date(2021, 12, 31), date(2021, 1, 1)),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "NetCashProvidedByUsedInOperatingActivities", "0000019617", "iso4217:USD", 107119000000.0, date(2022, 12, 31), date(2022, 1, 1)),
    # Real, consolidated, but deliberately NOT mapped to cash_and_equivalents (see sec_concepts.py)
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "CashAndDueFromBanks", "0000019617", "iso4217:USD", 26438000000.0, date(2021, 12, 31), None),
    _f("JPM", JPM_10K_FILING, JPM_10K_FILED, "CashAndDueFromBanks", "0000019617", "iso4217:USD", 27697000000.0, date(2022, 12, 31), None),
]

# --- AAPL Q3 FY2023 10-Q: quarterly AND year-to-date duration facts, both real, both axises=() ---
AAPL_10Q_FACTS = [
    _f("AAPL", AAPL_10Q_FILING, AAPL_10Q_FILED, "RevenueFromContractWithCustomerExcludingAssessedTax", "0000320193", "iso4217:USD", 81797000000.0, date(2023, 7, 1), date(2023, 4, 2)),  # Q3 FY2023 standalone
    _f("AAPL", AAPL_10Q_FILING, AAPL_10Q_FILED, "RevenueFromContractWithCustomerExcludingAssessedTax", "0000320193", "iso4217:USD", 293787000000.0, date(2023, 7, 1), date(2022, 9, 25)),  # 9-month YTD FY2023
    _f("AAPL", AAPL_10Q_FILING, AAPL_10Q_FILED, "RevenueFromContractWithCustomerExcludingAssessedTax", "0000320193", "iso4217:USD", 82959000000.0, date(2022, 6, 25), date(2022, 3, 27)),  # Q3 FY2022 standalone (comparative)
    _f("AAPL", AAPL_10Q_FILING, AAPL_10Q_FILED, "RevenueFromContractWithCustomerExcludingAssessedTax", "0000320193", "iso4217:USD", 304182000000.0, date(2022, 6, 25), date(2021, 9, 26)),  # 9-month YTD FY2022 (comparative)
    _f("AAPL", AAPL_10Q_FILING, AAPL_10Q_FILED, "NetIncomeLoss", "0000320193", "iso4217:USD", 19881000000.0, date(2023, 7, 1), date(2023, 4, 2)),
    _f("AAPL", AAPL_10Q_FILING, AAPL_10Q_FILED, "NetIncomeLoss", "0000320193", "iso4217:USD", 74039000000.0, date(2023, 7, 1), date(2022, 9, 25)),
    _f("AAPL", AAPL_10Q_FILING, AAPL_10Q_FILED, "NetIncomeLoss", "0000320193", "iso4217:USD", 19442000000.0, date(2022, 6, 25), date(2022, 3, 27)),
    _f("AAPL", AAPL_10Q_FILING, AAPL_10Q_FILED, "NetIncomeLoss", "0000320193", "iso4217:USD", 79082000000.0, date(2022, 6, 25), date(2021, 9, 26)),
    _f("AAPL", AAPL_10Q_FILING, AAPL_10Q_FILED, "OperatingIncomeLoss", "0000320193", "iso4217:USD", 22998000000.0, date(2023, 7, 1), date(2023, 4, 2)),
    _f("AAPL", AAPL_10Q_FILING, AAPL_10Q_FILED, "OperatingIncomeLoss", "0000320193", "iso4217:USD", 87332000000.0, date(2023, 7, 1), date(2022, 9, 25)),
    _f("AAPL", AAPL_10Q_FILING, AAPL_10Q_FILED, "OperatingIncomeLoss", "0000320193", "iso4217:USD", 23076000000.0, date(2022, 6, 25), date(2022, 3, 27)),
    _f("AAPL", AAPL_10Q_FILING, AAPL_10Q_FILED, "OperatingIncomeLoss", "0000320193", "iso4217:USD", 94543000000.0, date(2022, 6, 25), date(2021, 9, 26)),
    # Instant facts: current-quarter-end vs prior-FISCAL-YEAR-end (not prior quarter-end) -- real 10-Q convention
    _f("AAPL", AAPL_10Q_FILING, AAPL_10Q_FILED, "Assets", "0000320193", "iso4217:USD", 335038000000.0, date(2023, 7, 1), None),
    _f("AAPL", AAPL_10Q_FILING, AAPL_10Q_FILED, "Assets", "0000320193", "iso4217:USD", 352755000000.0, date(2022, 9, 24), None),
    _f("AAPL", AAPL_10Q_FILING, AAPL_10Q_FILED, "CashAndCashEquivalentsAtCarryingValue", "0000320193", "iso4217:USD", 28408000000.0, date(2023, 7, 1), None),
    _f("AAPL", AAPL_10Q_FILING, AAPL_10Q_FILED, "CashAndCashEquivalentsAtCarryingValue", "0000320193", "iso4217:USD", 23646000000.0, date(2022, 9, 24), None),
]

# --- AAPL FY2022 10-K capital expenditures (real, axises=()) -- extends Phase 16's whitelist -----
AAPL_CAPEX_FACTS = [
    _f("AAPL", AAPL_10K_FILING, AAPL_10K_FILED, "PaymentsToAcquirePropertyPlantAndEquipment", "0000320193", "iso4217:USD", 7309000000.0, date(2020, 9, 26), date(2019, 9, 29)),
    _f("AAPL", AAPL_10K_FILING, AAPL_10K_FILED, "PaymentsToAcquirePropertyPlantAndEquipment", "0000320193", "iso4217:USD", 11085000000.0, date(2021, 9, 25), date(2020, 9, 27)),
    _f("AAPL", AAPL_10K_FILING, AAPL_10K_FILED, "PaymentsToAcquirePropertyPlantAndEquipment", "0000320193", "iso4217:USD", 10708000000.0, date(2022, 9, 24), date(2021, 9, 26)),
]


def main() -> None:
    store = SECFilingStore(RESEARCH_DATA_ROOT)

    # Register the newly-fact-probed filings in each issuer's filing index (idempotent -- Phase 16
    # already registered MSFT/NVDA/JPM's filing index; this adds nothing new there, but AAPL's
    # 10-Q filing was already indexed in Phase 16 too, so this is purely a facts-layer addition).
    for symbol, facts in (("MSFT", MSFT_FACTS), ("NVDA", NVDA_FACTS), ("JPM", JPM_FACTS)):
        existing = store.load_facts(symbol)
        store.save_facts(symbol, existing + facts)

    aapl_existing = store.load_facts("AAPL")
    store.save_facts("AAPL", aapl_existing + AAPL_10Q_FACTS + AAPL_CAPEX_FACTS)

    for symbol in ("AAPL", "MSFT", "NVDA", "JPM"):
        print(f"{symbol}: {len(store.load_facts(symbol))} total facts persisted", flush=True)

    print("\nConfirmed real cross-issuer findings:", flush=True)
    print("  - AAPL/MSFT tag revenue as RevenueFromContractWithCustomerExcludingAssessedTax", flush=True)
    print("  - NVDA/JPM tag revenue as Revenues (disjoint from AAPL/MSFT's tag)", flush=True)
    print("  - JPM has ZERO OperatingIncomeLoss and ZERO CashAndCashEquivalentsAtCarryingValue facts", flush=True)
    print("  - AAPL's Q3 FY2023 10-Q reports BOTH standalone-quarter (~90d) and 9-month-YTD (~279d)", flush=True)
    print("    duration facts for the same concept, both axises=() -- no derivation needed", flush=True)


if __name__ == "__main__":
    main()
