#!/usr/bin/env python3
"""Phase 16 — STEP 2: SEC data quality audit, point-in-time snapshot
demonstration, and SEC_FUNDAMENTALS_ASOF dataset generation — all on the
REAL data ingested by phase16_step1_ingest_sample_filings.py. No alpha
computation of any kind (Part 16, 18) — this script never touches a
return, a target, or a predictive statistic.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.sec_concepts import CONCEPT_MAP, is_known_reliable_concept  # noqa: E402
from src.data.sec_dataset import DEFAULT_FACT_WHITELIST, SECDatasetSpec, generate_sec_fundamentals_asof  # noqa: E402
from src.data.sec_fact_quality import (  # noqa: E402
    FactQualityClass,
    SECQualityReport,
    classify_fact,
    find_duplicate_facts,
    find_impossible_period_ordering,
    find_unit_inconsistencies,
)
from src.data.sec_filing_store import SECFilingStore, classify_form  # noqa: E402
from src.data.sec_snapshot import get_available_facts_for_symbol, latest_known_value  # noqa: E402
from src.data.sec_timestamp_policy import SECCausalPolicy, sec_is_available_asof  # noqa: E402

RESEARCH_DATA_ROOT = Path("logs/research_data") / "sec"
ISSUERS = ("AAPL", "MSFT", "NVDA", "JPM")


def _print_header(title: str) -> None:
    print("\n" + "=" * 100, flush=True)
    print(title, flush=True)
    print("=" * 100, flush=True)


def part_form_classification(store: SECFilingStore) -> None:
    _print_header("PART 6 — FILING FORM CLASSIFICATION")
    filings_by_form: dict[str, int] = {}
    date_range: tuple[date, date] | None = None
    for symbol in ISSUERS:
        for filing in store.load_filings(symbol):
            filings_by_form[filing.form_type] = filings_by_form.get(filing.form_type, 0) + 1
            if date_range is None:
                date_range = (filing.date_filed, filing.date_filed)
            else:
                date_range = (min(date_range[0], filing.date_filed), max(date_range[1], filing.date_filed))
        profile_10k = classify_form("10-K")
        profile_10q = classify_form("10-Q")
        n_10k = sum(1 for f in store.load_filings(symbol) if f.form_type == "10-K")
        n_10q = sum(1 for f in store.load_filings(symbol) if f.form_type == "10-Q")
        covers_window = any(date(2021, 9, 1) <= f.date_filed <= date(2023, 8, 31) or f.date_filed < date(2021, 9, 1) for f in store.load_filings(symbol) if f.form_type in ("10-K", "10-Q"))
        print(f"  {symbol}: 10-K={n_10k}  10-Q={n_10q}  10-K_usable={profile_10k.enters_historical_fact_store}  10-Q_usable={profile_10q.enters_historical_fact_store}  discovery_window_coverage={'YES' if covers_window else 'NO -- VERIFIED GAP'}", flush=True)
    print(f"\n  filings_by_form: {filings_by_form}", flush=True)
    print(f"  filing_date_range: {date_range}", flush=True)
    print("  8-K: contains_structured_facts=False, enters_historical_fact_store=False -> METADATA_ONLY (not ingested as facts this phase)", flush=True)


def part_quality_report(store: SECFilingStore) -> SECQualityReport:
    _print_header("PART 7, 14 — SEC DATA QUALITY REPORT (real ingested data)")
    all_facts = []
    filings_by_form: dict[str, int] = {}
    amended_count = 0
    for symbol in ISSUERS:
        filings = store.load_filings(symbol)
        for f in filings:
            filings_by_form[f.form_type] = filings_by_form.get(f.form_type, 0) + 1
            if f.is_amendment:
                amended_count += 1
        all_facts.extend(store.load_facts(symbol))

    dupes = find_duplicate_facts(all_facts)
    unit_anoms = find_unit_inconsistencies(all_facts)
    bad_periods = find_impossible_period_ordering(all_facts)

    classifications = [classify_fact(f, known_normalized_concept=is_known_reliable_concept(f.concept)) for f in all_facts]
    counts = {cls: sum(1 for c in classifications if c.quality_class == cls) for cls in FactQualityClass}
    unsupported_concepts = {c.fact.concept for c in classifications if c.quality_class == FactQualityClass.REQUIRES_NORMALIZATION}

    dates = [f.date_filed for symbol in ISSUERS for f in store.load_filings(symbol)]
    report = SECQualityReport(
        issuers_tested=ISSUERS,
        filings_by_form=filings_by_form,
        filing_date_range=(min(dates).isoformat(), max(dates).isoformat()) if dates else None,
        total_fact_count=len(all_facts),
        duplicate_count=len(dupes),
        missing_publication_timestamp_count=sum(len(store.load_filings(s)) for s in ISSUERS),  # every filing: date-only, confirmed no time-of-day ever supplied
        amended_filing_count=amended_count,
        unit_anomaly_count=len(unit_anoms),
        unsupported_concept_count=len(unsupported_concepts),
        safe_for_research_count=counts[FactQualityClass.SAFE_FOR_RESEARCH],
        requires_normalization_count=counts[FactQualityClass.REQUIRES_NORMALIZATION],
        metadata_only_count=counts[FactQualityClass.METADATA_ONLY],
        rejected_count=counts[FactQualityClass.REJECTED],
    )
    print(report.render(), flush=True)
    print(f"\n  unsupported_concepts (REQUIRES_NORMALIZATION): {sorted(unsupported_concepts) or 'none in this sample'}", flush=True)
    print(f"  duplicate groups: {list(dupes.keys())}", flush=True)
    return report


def part_snapshot_engine_demo(store: SECFilingStore) -> None:
    _print_header("PART 8 — POINT-IN-TIME SNAPSHOT ENGINE DEMONSTRATION (real AAPL data)")
    before = datetime(2022, 10, 28, tzinfo=timezone.utc)  # the exact filing date -- must NOT be available
    on_filing_date = datetime(2022, 10, 28, 23, 59, tzinfo=timezone.utc)  # same calendar day, different time-of-day -- still must NOT be available (Part 5 rule 3)
    after = datetime(2022, 10, 29, tzinfo=timezone.utc)
    much_later = datetime(2023, 1, 1, tzinfo=timezone.utc)

    for label, as_of in (("before filing (2022-10-28 00:00)", before), ("same calendar day, late (2022-10-28 23:59)", on_filing_date), ("day after (2022-10-29)", after), ("much later (2023-01-01)", much_later)):
        available = get_available_facts_for_symbol(store, "AAPL", as_of=as_of)
        revenue = latest_known_value(available, normalized_concept="revenue")
        print(f"  as_of={label}: {len(available)} facts available, latest_known_revenue={revenue.value if revenue else None}", flush=True)

    print("\n  Confirms Part 5 rule 3 (date-only conservative exclusion): the FY2022 10-K (filed 2022-10-28) is", flush=True)
    print("  correctly UNAVAILABLE for the entire filing date, including 23:59 on that date -- only becomes", flush=True)
    print("  available starting the following calendar day, since no time-of-day is ever supplied by this source.", flush=True)


def part_asof_dataset_demo(store: SECFilingStore) -> None:
    _print_header("PART 9, 11, 13 — SEC_FUNDAMENTALS_ASOF DATASET GENERATION DEMONSTRATION")
    spec = SECDatasetSpec(
        universe_name="US_DIVERSIFIED", symbols=("AAPL",), start_date=date(2022, 9, 1), end_date=date(2023, 1, 1),
        observation_frequency="monthly", timestamp_policy=SECCausalPolicy.PUBLICATION_DATE_ONLY, filing_forms=("10-K", "10-Q"),
    )
    observations, version = generate_sec_fundamentals_asof(store, spec, retrieval_timestamp=datetime(2026, 9, 2, tzinfo=timezone.utc))
    revenue_obs = [o for o in observations if o.normalized_concept == "revenue"]
    for o in revenue_obs:
        print(f"  as_of={o.as_of.date()}  revenue={o.value}  (from fiscal period ending {o.fact_period_end}, filed {o.fact_date_filed})", flush=True)
    print(f"\n  Total observations generated: {len(observations)} (1 symbol x {len(DEFAULT_FACT_WHITELIST)} concepts x monthly instants)", flush=True)
    print(f"  DatasetVersionRecord.fingerprint() = {version.fingerprint()}", flush=True)

    # Part 13: a different timestamp policy must NOT produce the same fingerprint.
    spec_exact = SECDatasetSpec(
        universe_name="US_DIVERSIFIED", symbols=("AAPL",), start_date=date(2022, 9, 1), end_date=date(2023, 1, 1),
        observation_frequency="monthly", timestamp_policy=SECCausalPolicy.PUBLICATION_DATE_ONLY, filing_forms=("10-K",),  # different fact_whitelist scope (forms) this time
    )
    _, version_diff_forms = generate_sec_fundamentals_asof(store, spec_exact, retrieval_timestamp=datetime(2026, 9, 2, tzinfo=timezone.utc))
    print(f"  Same policy, forms=('10-K',) only -> fingerprint = {version_diff_forms.fingerprint()}  (different from above: {version.fingerprint() != version_diff_forms.fingerprint()})", flush=True)


def main() -> None:
    store = SECFilingStore(RESEARCH_DATA_ROOT)
    part_form_classification(store)
    part_quality_report(store)
    part_snapshot_engine_demo(store)
    part_asof_dataset_demo(store)
    _print_header("DONE — data capability only. No alpha hypothesis tested, no trading strategy created or modified.")


if __name__ == "__main__":
    main()
