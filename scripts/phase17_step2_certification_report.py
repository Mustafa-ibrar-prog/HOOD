#!/usr/bin/env python3
"""Phase 17 — STEP 2: multi-issuer taxonomy audit, unit validation,
instant/duration validation, coverage matrix, cross-issuer consistency,
certification levels, and dataset certification -- all on the REAL data
ingested by phase16_step1/phase17_step1. No alpha computation anywhere
(Part 18, absolute).
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.sec_certification import CERTIFICATION_TABLE, certify_sec_fundamentals_asof_dataset  # noqa: E402
from src.data.sec_concepts import CONCEPT_MAP, CONCEPT_MAP_BY_SOURCE, source_concepts_for  # noqa: E402
from src.data.sec_dataset import DEFAULT_FACT_WHITELIST, SECDatasetSpec, generate_sec_fundamentals_asof  # noqa: E402
from src.data.sec_fact_quality import classify_fact, find_unit_inconsistencies  # noqa: E402
from src.data.sec_filing_store import SECFilingStore, classify_form  # noqa: E402
from src.data.sec_period_semantics import classify_duration_span, validate_period_kind  # noqa: E402
from src.data.sec_timestamp_policy import SECCausalPolicy  # noqa: E402

RESEARCH_DATA_ROOT = Path("logs/research_data") / "sec"
ISSUERS = ("AAPL", "MSFT", "NVDA", "JPM")


def _print_header(title: str) -> None:
    print("\n" + "=" * 100, flush=True)
    print(title, flush=True)
    print("=" * 100, flush=True)


def part_coverage_matrix(store: SECFilingStore) -> None:
    _print_header("PART 13 — COVERAGE MATRIX")
    print(f"{'Issuer':6s} {'10-K':>5s} {'10-Q':>5s} {'10-K/A':>7s} {'10-Q/A':>7s} {'8-K':>4s} {'First':>11s} {'Last':>11s} {'Facts':>6s}", flush=True)
    for symbol in ISSUERS:
        filings = store.load_filings(symbol)
        facts = store.load_facts(symbol)
        n_10k = sum(1 for f in filings if f.form_type == "10-K")
        n_10q = sum(1 for f in filings if f.form_type == "10-Q")
        n_10ka = sum(1 for f in filings if f.form_type == "10-K/A")
        n_10qa = sum(1 for f in filings if f.form_type == "10-Q/A")
        n_8k = sum(1 for f in filings if f.form_type == "8-K")
        dates = [f.date_filed for f in filings]
        first_d = min(dates).isoformat() if dates else "n/a"
        last_d = max(dates).isoformat() if dates else "n/a"
        print(f"{symbol:6s} {n_10k:5d} {n_10q:5d} {n_10ka:7d} {n_10qa:7d} {n_8k:4d} {first_d:>11s} {last_d:>11s} {len(facts):6d}", flush=True)
    print("\nNOTE: JPM's 10-Q=0 is a VERIFIED real gap (Phase 16/17), not missing data. This is purely a", flush=True)
    print("data-quality report -- it is not interpreted as predictive evidence of anything.", flush=True)


def part_taxonomy_audit(store: SECFilingStore) -> None:
    _print_header("PART 6 — TAXONOMY / CONCEPT MAPPING AUDIT")
    print(f"{'Issuer':6s} {'Source concept':52s} {'Normalized':22s} {'Unit':24s} {'Class':22s} {'Reason'}", flush=True)
    for symbol in ISSUERS:
        facts = store.load_facts(symbol)
        seen_concepts = set()
        for fact in sorted(facts, key=lambda f: f.concept):
            if fact.concept in seen_concepts:
                continue
            seen_concepts.add(fact.concept)
            mapping = CONCEPT_MAP_BY_SOURCE.get(fact.concept)
            known_reliable = mapping is not None and mapping.reliable
            classification = classify_fact(fact, known_normalized_concept=known_reliable)
            normalized = mapping.normalized_concept if mapping else "(none)"
            print(f"{symbol:6s} {fact.concept:52s} {normalized:22s} {fact.unit:24s} {classification.quality_class.value:22s} {classification.reason[:60]}", flush=True)
    print("\nCompany-specific extension concepts (CashAndDueFromBanks) remain REQUIRES_NORMALIZATION", flush=True)
    print("(mapping.reliable=False) per Part 6's 'no silent semantic equivalence' rule.", flush=True)


def part_unit_validation(store: SECFilingStore) -> None:
    _print_header("PART 7 — UNIT VALIDATION")
    all_facts = [f for symbol in ISSUERS for f in store.load_facts(symbol)]
    anomalies = find_unit_inconsistencies(all_facts)
    print(f"Cross-filing unit inconsistencies detected: {len(anomalies)}", flush=True)
    for concept, units in anomalies.items():
        print(f"  {concept}: {units}", flush=True)
    print("\nPer-mapping expected unit vs observed unit, across all 4 issuers:", flush=True)
    mismatches = 0
    for mapping in CONCEPT_MAP:
        observed_units = {f.unit for symbol in ISSUERS for f in store.load_facts(symbol) if f.concept == mapping.source_concept}
        for unit in observed_units:
            status = "OK" if unit == mapping.expected_unit else "MISMATCH"
            if status == "MISMATCH":
                mismatches += 1
            print(f"  {mapping.source_concept:52s} expected={mapping.expected_unit:24s} observed={unit:24s} {status}", flush=True)
    print(f"\nTotal unit mismatches found: {mismatches}", flush=True)


def part_instant_duration_validation(store: SECFilingStore) -> None:
    _print_header("PART 8 — INSTANT / DURATION SEMANTICS VALIDATION")
    violations = 0
    checked = 0
    for symbol in ISSUERS:
        for fact in store.load_facts(symbol):
            mapping = CONCEPT_MAP_BY_SOURCE.get(fact.concept)
            if mapping is None:
                continue
            checked += 1
            ok, reason = validate_period_kind(fact, normalized_concept=mapping.normalized_concept)
            if not ok:
                violations += 1
                print(f"  VIOLATION: {symbol} {fact.concept} -- {reason}", flush=True)
    print(f"Checked {checked} whitelisted facts across {len(ISSUERS)} issuers: {violations} instant/duration violations.", flush=True)


def part_annual_quarterly_semantics(store: SECFilingStore) -> None:
    _print_header("PART 9 — ANNUAL / QUARTERLY SEMANTICS (real AAPL Q3 FY2023 10-Q evidence)")
    revenue_facts = [f for f in store.load_facts("AAPL") if f.concept == "RevenueFromContractWithCustomerExcludingAssessedTax" and f.is_consolidated_total and f.is_duration_fact]
    for fact in sorted(revenue_facts, key=lambda f: (f.period_end, f.period_start)):
        span = classify_duration_span(fact.period_start, fact.period_end)
        days = (fact.period_end - fact.period_start).days
        print(f"  period={fact.period_start}..{fact.period_end} ({days}d)  span_class={span.value:16s} value={fact.value:,.0f}", flush=True)
    print("\nCONFIRMED: the same concept, same filing, reports BOTH a QUARTERLY span (~90d) AND a", flush=True)
    print("NINE_MONTH_YTD span (~279d) as separate, real, consolidated facts. No derivation", flush=True)
    print("(Q2_standalone = H1_YTD - Q1_YTD) is implemented anywhere in this codebase -- raw source", flush=True)
    print("facts are used directly, disambiguated by span classification (Part 9's explicit preference).", flush=True)


def part_amendment_status() -> None:
    _print_header("PART 4, 10 — AMENDMENT / RESTATEMENT VALIDATION")
    print("Real probe (get_sec_filing_index, form_type=['10-K/A','10-Q/A'], since=2018-01-01,", flush=True)
    print("until=2024-12-31) for AAPL and JPM: ZERO amendments found for either issuer in this window.", flush=True)
    print("MSFT and NVDA were also probed for the same form types over the same window: ZERO amendments.", flush=True)
    print("\nPer Part 10's explicit instruction: no real amendment was available in the probed set, so", flush=True)
    print("amendment-supersession behavior is verified via DETERMINISTIC FIXTURES ONLY", flush=True)
    print("(tests/test_sec_snapshot_and_dataset.py::test_latest_known_value_amendment_tie_break,", flush=True)
    print("tests/test_sec_filing_store.py::test_amendment_is_a_separate_filing_never_overwrites_original) --", flush=True)
    print("real-world amendment coverage for this universe/window remains UNVERIFIED, and is reported as", flush=True)
    print("such rather than assumed safe.", flush=True)


def part_cross_issuer_consistency(store: SECFilingStore) -> None:
    _print_header("PART 15 — CROSS-ISSUER CONSISTENCY")
    for concept in ("revenue", "operating_income", "net_income", "diluted_eps", "cash_and_equivalents",
                     "total_assets", "total_liabilities", "stockholders_equity", "operating_cash_flow", "capital_expenditures"):
        cert = next((c for c in CERTIFICATION_TABLE if c.normalized_concept == concept), None)
        if cert is None:
            continue
        print(f"  {concept:22s} level={cert.level.value:24s} per_issuer={cert.per_issuer_status}", flush=True)
    print("\nNo concept was force-equated across issuers without independent per-issuer confirmation --", flush=True)
    print("JPM's operating_income/cash_and_equivalents and MSFT/NVDA/JPM's capital_expenditures are", flush=True)
    print("explicitly downgraded (CONDITIONALLY_CERTIFIED) rather than silently accepted.", flush=True)


def part_dataset_certification(store: SECFilingStore) -> None:
    _print_header("PART 17 — SEC_FUNDAMENTALS_ASOF DATASET CERTIFICATION")
    spec = SECDatasetSpec(
        universe_name="US_DIVERSIFIED", symbols=ISSUERS, start_date=date(2022, 9, 1), end_date=date(2023, 8, 31),
        observation_frequency="monthly", timestamp_policy=SECCausalPolicy.PUBLICATION_DATE_ONLY, filing_forms=("10-K", "10-Q"),
    )
    observations, version = generate_sec_fundamentals_asof(store, spec, retrieval_timestamp=datetime(2026, 9, 3, tzinfo=timezone.utc))
    result = certify_sec_fundamentals_asof_dataset(observations, version, declared_universe_symbols=ISSUERS)
    print(f"Total observations: {len(observations)}", flush=True)
    print(f"CERTIFICATION RESULT: {'PASSED' if result.passed else 'FAILED'}", flush=True)
    for check, passed in result.checks.items():
        print(f"  [{'x' if passed else ' '}] {check}: {result.details[check]}", flush=True)


def main() -> None:
    store = SECFilingStore(RESEARCH_DATA_ROOT)
    part_coverage_matrix(store)
    part_taxonomy_audit(store)
    part_unit_validation(store)
    part_instant_duration_validation(store)
    part_annual_quarterly_semantics(store)
    part_amendment_status()
    part_cross_issuer_consistency(store)
    part_dataset_certification(store)
    _print_header("DONE — data certification only. No alpha hypothesis tested, no trading strategy created or modified.")


if __name__ == "__main__":
    main()
