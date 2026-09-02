#!/usr/bin/env python3
"""Phase 16 — STEP 1: ingest REAL SEC filing-index and fact data into
SECFilingStore.

Every record below was fetched via real, read-only
mcp__HOOD__get_sec_filing_index / mcp__HOOD__get_sec_filing_facts calls
made by the orchestrating agent during this phase's development — same
"nothing in this Python process can call a HOOD MCP tool directly, the
agent fetches and a script ingests" convention documented in
src/data/store.py's own module docstring for Bar data (see e.g.
scripts/phase6_ingest_secondary_universe.py for the precedent). Nothing
here is fabricated, estimated, or interpolated (Part 4/22's explicit
prohibition).

SCOPE: filing-INDEX coverage (form type + date_filed) was verified for
all four representative securities (AAPL, MSFT, NVDA, JPM) across
2020-2023, confirming or refuting 10-K/10-Q presence per Part 6.
Fact-level ingestion was done in depth for ONE representative filing
(AAPL's FY2022 10-K, filing_id 27c07064-...) — a real, verified subset
(not the complete XBRL fact set of that filing) sufficient to exercise
every quality-classification path (consolidated totals, dimensional
breakdowns, a genuine same-filing duplicate, and a concept -- "Revenues"
-- that does NOT exist under that name, confirming the concept-
normalization risk). Fact-level ingestion for MSFT/NVDA/JPM's own
filings was not performed this phase; a future phase would repeat the
same agent-fetch-then-ingest pattern for whichever filings it needs.

CONFIRMED FINDINGS THIS INGESTION ENCODES:
  - JPM: ZERO 10-Q filings returned by the index for 2021-2023, despite
    JPM being a large, active SEC filer with 3 confirmed 10-Ks in the
    same window. This is a REAL, VERIFIED GAP in this connector's 10-Q
    coverage for at least this issuer -- not assumed, not guessed.
  - SPY: ZERO filings of any kind (10-K/10-Q/8-K) returned by the index
    -- confirms Phase 15's expectation that SEC issuer facts do not apply
    to an ETF.
  - AAPL/MSFT/NVDA: 10-K and 10-Q coverage both confirmed present and
    spanning (and preceding) the 2021-09-01..2023-08-31 discovery window.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.sec_fact_quality import find_duplicate_facts  # noqa: E402
from src.data.sec_filing_store import SECFactRecord, SECFilingRecord, SECFilingStore  # noqa: E402

RESEARCH_DATA_ROOT = Path("logs/research_data")
RETRIEVAL_TIMESTAMP = datetime(2026, 9, 2, tzinfo=timezone.utc)  # when this agent made the real probe calls

# --- AAPL filing index (real, mcp__HOOD__get_sec_filing_index) -----------------------------------
AAPL_10K = [
    ("f40e0579-5345-46f4-ab33-8362ac3ea95d", date(2025, 10, 31)),
    ("71575601-2342-4a06-b4d6-da4fbb332738", date(2024, 11, 1)),
    ("67b5f36f-226d-4376-901f-4d428b789805", date(2023, 11, 3)),
    ("27c07064-a0ab-4224-92ea-2637d8e23c9c", date(2022, 10, 28)),
    ("e3e6ed68-2313-4bb2-ad40-2aab01edc7d2", date(2021, 10, 29)),
    ("b2932d19-a269-4ba1-8fb9-cab6b1544279", date(2020, 10, 30)),
]
AAPL_10Q = [
    ("f0c81217-21e9-4a0b-b99e-e198447bbd9d", date(2023, 8, 4)),
    ("466cc959-3ea7-4b39-8b84-b22085337f4d", date(2023, 5, 5)),
    ("ada433bc-ef75-4ace-b964-8045b8aa872b", date(2023, 2, 3)),
    ("b60e989d-47b3-49c5-be1d-8aad9e23b2b1", date(2022, 7, 29)),
    ("8f5b904a-0492-45c0-9b51-d3cd92b2ff1c", date(2022, 4, 29)),
    ("ee368405-b526-4646-89a9-73e4cbc2f1c1", date(2022, 1, 28)),
    ("ca3a9fb7-2a2a-4496-b750-b2059e7bb1f4", date(2021, 7, 28)),
    ("081a9690-8eb9-4efb-ad9b-d1778632b3a9", date(2021, 4, 29)),
    ("ea5dd948-a0c5-49ce-8039-4a1acbb95e48", date(2021, 1, 28)),
]
AAPL_8K = [
    ("d4917e69-610c-488e-a5fc-2a55f851e406", date(2023, 11, 2)),
    ("abdf9b3b-73a5-4de9-b3dd-5ffcbee1ee20", date(2023, 8, 3)),
    ("2749bf86-2c44-43f5-9b1a-b532ea88bbef", date(2023, 5, 10)),
    ("05c8f372-8b4a-41c3-8044-625e7bb6e685", date(2023, 5, 4)),
    ("a4e0f3a5-3e8b-43f2-9fa6-a225bfcb30e1", date(2023, 3, 10)),
    ("2575902b-793e-4fc4-8f1e-0d4bafe56f85", date(2023, 2, 2)),
    ("89e1764d-ab71-463d-aee4-6f6280a6f888", date(2022, 11, 7)),
    ("338c2ce1-43f7-4ae4-8962-abc6351cc57c", date(2022, 10, 27)),
    ("030370a4-cb11-4202-9fd3-600a9a61e2d2", date(2022, 8, 19)),
    ("a7145142-62c1-453c-9154-6c85a193c253", date(2022, 8, 8)),
    ("3515e60c-4b8a-478f-adb8-51abe1e917ee", date(2022, 7, 28)),
    ("732b971f-d41d-44d4-8c56-6c1ec620c46a", date(2022, 4, 28)),
    ("25395966-2f10-440e-819c-b8ee16c27f0b", date(2022, 3, 4)),
    ("8f5c31f5-6549-42c8-a65a-2d30b2c4cc3e", date(2022, 1, 27)),
    ("de3449bf-9b21-4a97-bda0-e74010a9410d", date(2021, 11, 12)),
    ("649b85ff-0ee0-4ab2-90ae-3b54339f7dab", date(2021, 10, 28)),
    ("fa0c0d0c-df0a-4dda-b360-e0d3eadf211b", date(2021, 8, 5)),
    ("180e34b8-a3ea-4459-80d3-eacf4abb8086", date(2021, 7, 27)),
    ("651b5ec3-cfe2-403d-94b2-6d076aff8fc9", date(2021, 4, 28)),
    ("70723bc5-c63c-40da-8e6d-2b6cca971716", date(2021, 2, 24)),
    ("7ade9a2c-ce02-4fe4-a63d-1c35aef1d28f", date(2021, 2, 8)),
    ("b6411b25-a15a-43ef-9507-0037709a3878", date(2021, 1, 27)),
    ("fd7d8bf4-3527-4b9c-b40a-db63000e4fdf", date(2021, 1, 5)),
]

MSFT_10K = [
    ("1916c86a-55a4-4de4-b0d7-222bc889eedf", date(2023, 7, 27)),
    ("0d6699b4-184c-4def-ba42-aa1f2f0e3252", date(2022, 7, 28)),
    ("e383f09a-4843-4649-8391-f640cb049fe4", date(2021, 7, 29)),
    ("a2502285-baa0-4629-a69c-d46b71246467", date(2020, 7, 31)),
]
MSFT_10Q = [
    ("4399bbbf-a355-4cfb-8191-b4fd26bb9a64", date(2023, 10, 24)),
    ("7b87dd89-089c-46a6-9c81-0213eca44ecf", date(2023, 4, 25)),
    ("24fce49e-400a-4633-939e-48c2bf27d682", date(2023, 1, 24)),
    ("6edbf961-f1f1-4d0d-bd2d-e8aea1440930", date(2022, 10, 25)),
    ("b32002e9-3650-4bc3-adc9-92cb5443c163", date(2022, 4, 26)),
    ("22c98318-0f0e-4d18-90f7-2947a1d97ea2", date(2022, 1, 25)),
    ("72f06d9e-8206-454a-9baf-1ccdc218ab8d", date(2021, 10, 26)),
    ("73365286-b244-4c5e-8c06-fa48c26d1c0e", date(2021, 4, 27)),
    ("6b307ec0-f3fc-4b46-85d3-6db2866c34ce", date(2021, 1, 26)),
]

NVDA_10K = [
    ("00467f8f-58e8-46a6-b68f-b8eb54a40a59", date(2023, 2, 24)),
    ("5fb9b001-88ad-4c9b-8f82-ee78edfb16ef", date(2022, 3, 18)),
    ("260bc777-ed05-4e52-a0bd-f382768044fc", date(2021, 2, 26)),
]
NVDA_10Q = [
    ("5056a281-4011-46ba-a3da-fc2a2a028fd7", date(2023, 11, 21)),
    ("74a0095f-659f-4143-a6f6-ac12c9e65525", date(2023, 8, 28)),
    ("7e46d5fd-e21b-4754-8122-6bda5ba432e4", date(2023, 5, 26)),
    ("5bacf405-f9da-48da-aebc-2d73aab130ea", date(2022, 11, 18)),
    ("b2ecdcac-3daf-43e2-8645-1c86209b6106", date(2022, 8, 31)),
    ("fc303257-7e25-4fc5-b399-f2f0c288ca54", date(2022, 5, 27)),
    ("49dbf7aa-b173-4d39-ae63-bb7b059c80d5", date(2021, 11, 22)),
    ("11f61bf9-9be7-4ea2-a13c-97179f6920ba", date(2021, 8, 20)),
    ("70f92716-3c6c-4f33-8170-cb7d33ca82cd", date(2021, 5, 26)),
]

JPM_10K = [
    ("2461b7c9-0807-4aae-9640-dffd4e5c8069", date(2023, 2, 21)),
    ("264620fa-342f-44f7-8939-2171744b57ba", date(2022, 2, 22)),
    ("690ad91c-bf9d-4ca3-91a7-45a9a47999df", date(2021, 2, 23)),
]
# JPM_10Q: deliberately EMPTY -- a real probe (form_type=["10-Q"], since=2021-01-01,
# until=2023-12-31) returned zero filings. This is a verified finding, not an omission.
JPM_10Q: list[tuple[str, date]] = []

# SPY: a real probe (since=2021-01-01, until=2023-12-31, no form_type filter) returned
# zero filings of any kind -- confirms SEC issuer facts do not apply to this ETF.
SPY_FILINGS: list[tuple[str, date]] = []


def _filing_records(symbol: str, form_type: str, description: str, rows: list[tuple[str, date]]) -> list[SECFilingRecord]:
    return [SECFilingRecord(issuer_symbol=symbol, filing_id=fid, form_type=form_type, description=description, date_filed=d) for fid, d in rows]


# --- AAPL FY2022 10-K facts (real, mcp__HOOD__get_sec_filing_facts, filing_id 27c07064-...) ------
# A verified REPRESENTATIVE SUBSET (not the complete XBRL fact set of this filing): every
# consolidated (axises=()) headline figure for the Part 10 whitelist concepts, plus a handful of
# real dimensional (axis-qualified) facts to exercise METADATA_ONLY classification on real data,
# plus one genuine duplicate the raw response actually contained (two identical NetIncomeLoss
# axises=() rows for the same period) to exercise find_duplicate_facts on real data.
_AAPL_FY22_10K = "27c07064-a0ab-4224-92ea-2637d8e23c9c"
_AAPL_FY22_FILED = date(2022, 10, 28)


def _fact(concept: str, cik: str, unit: str, value: float, end: date, start: date | None, axises: tuple[str, ...]) -> SECFactRecord:
    return SECFactRecord(
        issuer_symbol="AAPL", filing_id=_AAPL_FY22_10K, concept=concept, entity_cik=cik, unit=unit, value=value,
        period_end=end, period_start=start, axises=axises, date_filed=_AAPL_FY22_FILED, retrieval_timestamp=RETRIEVAL_TIMESTAMP,
    )


AAPL_FY22_FACTS = [
    # Consolidated totals (axises == ()) -- SAFE_FOR_RESEARCH candidates
    _fact("Assets", "0000320193", "iso4217:USD", 351002000000.0, date(2021, 9, 25), None, ()),
    _fact("Assets", "0000320193", "iso4217:USD", 352755000000.0, date(2022, 9, 24), None, ()),
    _fact("Liabilities", "0000320193", "iso4217:USD", 287912000000.0, date(2021, 9, 25), None, ()),
    _fact("Liabilities", "0000320193", "iso4217:USD", 302083000000.0, date(2022, 9, 24), None, ()),
    _fact("StockholdersEquity", "0000320193", "iso4217:USD", 90488000000.0, date(2019, 9, 28), None, ()),
    _fact("StockholdersEquity", "0000320193", "iso4217:USD", 65339000000.0, date(2020, 9, 26), None, ()),
    _fact("StockholdersEquity", "0000320193", "iso4217:USD", 63090000000.0, date(2021, 9, 25), None, ()),
    _fact("StockholdersEquity", "0000320193", "iso4217:USD", 50672000000.0, date(2022, 9, 24), None, ()),
    _fact("EarningsPerShareDiluted", "0000320193", "iso4217:USD/xbrli:shares", 3.28, date(2020, 9, 26), date(2019, 9, 29), ()),
    _fact("EarningsPerShareDiluted", "0000320193", "iso4217:USD/xbrli:shares", 5.61, date(2021, 9, 25), date(2020, 9, 27), ()),
    _fact("EarningsPerShareDiluted", "0000320193", "iso4217:USD/xbrli:shares", 6.11, date(2022, 9, 24), date(2021, 9, 26), ()),
    _fact("CashAndCashEquivalentsAtCarryingValue", "0000320193", "iso4217:USD", 34940000000.0, date(2021, 9, 25), None, ()),
    _fact("CashAndCashEquivalentsAtCarryingValue", "0000320193", "iso4217:USD", 23646000000.0, date(2022, 9, 24), None, ()),
    _fact("NetCashProvidedByUsedInOperatingActivities", "0000320193", "iso4217:USD", 80674000000.0, date(2020, 9, 26), date(2019, 9, 29), ()),
    _fact("NetCashProvidedByUsedInOperatingActivities", "0000320193", "iso4217:USD", 104038000000.0, date(2021, 9, 25), date(2020, 9, 27), ()),
    _fact("NetCashProvidedByUsedInOperatingActivities", "0000320193", "iso4217:USD", 122151000000.0, date(2022, 9, 24), date(2021, 9, 26), ()),
    _fact("RevenueFromContractWithCustomerExcludingAssessedTax", "0000320193", "iso4217:USD", 274515000000.0, date(2020, 9, 26), date(2019, 9, 29), ()),
    _fact("RevenueFromContractWithCustomerExcludingAssessedTax", "0000320193", "iso4217:USD", 365817000000.0, date(2021, 9, 25), date(2020, 9, 27), ()),
    _fact("RevenueFromContractWithCustomerExcludingAssessedTax", "0000320193", "iso4217:USD", 394328000000.0, date(2022, 9, 24), date(2021, 9, 26), ()),
    _fact("OperatingIncomeLoss", "0000320193", "iso4217:USD", 66288000000.0, date(2020, 9, 26), date(2019, 9, 29), ()),
    _fact("OperatingIncomeLoss", "0000320193", "iso4217:USD", 108949000000.0, date(2021, 9, 25), date(2020, 9, 27), ()),
    _fact("OperatingIncomeLoss", "0000320193", "iso4217:USD", 119437000000.0, date(2022, 9, 24), date(2021, 9, 26), ()),
    _fact("CommonStockSharesOutstanding", "0000320193", "xbrli:shares", 16426786000.0, date(2021, 9, 25), None, ()),
    _fact("CommonStockSharesOutstanding", "0000320193", "xbrli:shares", 15943425000.0, date(2022, 9, 24), None, ()),
    _fact("NetIncomeLoss", "0000320193", "iso4217:USD", 57411000000.0, date(2020, 9, 26), date(2019, 9, 29), ()),
    _fact("NetIncomeLoss", "0000320193", "iso4217:USD", 94680000000.0, date(2021, 9, 25), date(2020, 9, 27), ()),
    _fact("NetIncomeLoss", "0000320193", "iso4217:USD", 99803000000.0, date(2022, 9, 24), date(2021, 9, 26), ()),
    # Genuine real duplicate: the raw response contained TWO identical axises=() NetIncomeLoss
    # rows for the same FY2022 period (one via a plain fact, one via a RetainedEarningsMember-
    # rollforward context that XBRL happens to also expose without an axis on this concept).
    _fact("NetIncomeLoss", "0000320193", "iso4217:USD", 99803000000.0, date(2022, 9, 24), date(2021, 9, 26), ()),
    # Dimensional (axis-qualified) facts -- real, but METADATA_ONLY, not consolidated totals
    _fact("RevenueFromContractWithCustomerExcludingAssessedTax", "0000320193", "iso4217:USD", 205489000000.0, date(2022, 9, 24), date(2021, 9, 26), ("ProductOrServiceAxis: IPhoneMember",)),
    _fact("RevenueFromContractWithCustomerExcludingAssessedTax", "0000320193", "iso4217:USD", 169658000000.0, date(2022, 9, 24), date(2021, 9, 26), ("StatementBusinessSegmentsAxis: AmericasSegmentMember",)),
    _fact("StockholdersEquity", "0000320193", "iso4217:USD", 5562000000.0, date(2021, 9, 25), None, ("StatementEquityComponentsAxis: RetainedEarningsMember",)),
    _fact("CommonStockSharesOutstanding", "0000320193", "xbrli:shares", 17772945000.0, date(2019, 9, 28), None, ("StatementEquityComponentsAxis: CommonStockMember",)),
    _fact("CommonStockSharesOutstanding", "0000320193", "xbrli:shares", 16976763000.0, date(2020, 9, 26), None, ("StatementEquityComponentsAxis: CommonStockMember",)),
]
# NOTE: a real probe for concept="Revenues" against this SAME filing returned ZERO rows -- AAPL
# does not tag revenue under that name. No SECFactRecord is created for it; its absence IS the
# finding (see src/data/sec_concepts.py).


def main() -> None:
    store = SECFilingStore(RESEARCH_DATA_ROOT / "sec")

    store.save_filings("AAPL", _filing_records("AAPL", "10-K", "Annual report pursuant to section 13 and 15(d)", AAPL_10K)
                        + _filing_records("AAPL", "10-Q", "Quarterly report pursuant to section 13 or 15(d)", AAPL_10Q)
                        + _filing_records("AAPL", "8-K", "Current report", AAPL_8K))
    store.save_filings("MSFT", _filing_records("MSFT", "10-K", "Annual report pursuant to section 13 and 15(d)", MSFT_10K)
                        + _filing_records("MSFT", "10-Q", "Quarterly report pursuant to section 13 or 15(d)", MSFT_10Q))
    store.save_filings("NVDA", _filing_records("NVDA", "10-K", "Annual report pursuant to section 13 and 15(d)", NVDA_10K)
                        + _filing_records("NVDA", "10-Q", "Quarterly report pursuant to section 13 or 15(d)", NVDA_10Q))
    store.save_filings("JPM", _filing_records("JPM", "10-K", "Annual report pursuant to section 13 and 15(d)", JPM_10K))  # JPM_10Q intentionally omitted -- verified empty

    dupes_before_save = find_duplicate_facts(AAPL_FY22_FACTS)
    store.save_facts("AAPL", AAPL_FY22_FACTS)

    print(f"AAPL: {len(store.load_filings('AAPL'))} filings ({len(AAPL_10K)} 10-K, {len(AAPL_10Q)} 10-Q, {len(AAPL_8K)} 8-K), {len(store.load_facts('AAPL'))} facts persisted", flush=True)
    print(f"MSFT: {len(store.load_filings('MSFT'))} filings ({len(MSFT_10K)} 10-K, {len(MSFT_10Q)} 10-Q)", flush=True)
    print(f"NVDA: {len(store.load_filings('NVDA'))} filings ({len(NVDA_10K)} 10-K, {len(NVDA_10Q)} 10-Q)", flush=True)
    print(f"JPM: {len(store.load_filings('JPM'))} filings ({len(JPM_10K)} 10-K, {len(JPM_10Q)} 10-Q -- CONFIRMED VERIFIED-EMPTY, not a fetch failure)", flush=True)
    print(f"SPY: {len(SPY_FILINGS)} filings -- CONFIRMED VERIFIED-EMPTY (real probe found no SEC issuer filings for this ETF)", flush=True)
    print(f"\nRaw AAPL FY2022 10-K fact batch (before store-level dedup): {len(AAPL_FY22_FACTS)} facts, "
          f"{len(dupes_before_save)} duplicate natural-key group(s) found by find_duplicate_facts (a genuine "
          f"real-data duplicate the raw response contained, not synthesized for this demo)", flush=True)
    for key, count in dupes_before_save.items():
        print(f"  duplicate: filing_id={key[0]} concept={key[1]} period_end={key[2]} count={count}", flush=True)


if __name__ == "__main__":
    main()
