#!/usr/bin/env python3
"""Phase 15 — DATA EXPANSION / ALPHA-SOURCE ARCHITECTURE AUDIT.

This is NOT a discovery script. It builds no features, registers no
hypothesis, computes no IC/Sharpe/PBO/DSR, and never touches
VALIDATION_DATA/FINAL_HOLDOUT_DATA. It does three things:

  1. Confirms the current baseline (Part 2) is unchanged: daily OHLCV,
     US_DIVERSIFIED, 2021-09-01..2026-08-31 stored, split-adjusted/
     dividend-unadjusted, CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED.
  2. Prints the Robinhood capability audit (Part 6) and the data-source
     provenance matrix (Part 5, src/data/source_profile.py's
     DATA_SOURCE_MATRIX) — the structured conclusion of real, read-only
     probe calls made against the connected HOOD tools during this
     phase's development (see each row's major_caveat for the exact
     evidence; e.g. a real get_equity_historicals(interval="minute")
     call ~2 years back returned only interpolated=true, zero-volume
     placeholder bars, not observations — this script does NOT re-issue
     those calls itself, since no Python process in this codebase is
     permitted to call a HOOD MCP tool directly, same boundary
     src/live_bridge.py's module docstring already documents).
  3. Demonstrates the new architecture (Part 12-15: timestamp model,
     versioning model, generic quality checks, store interfaces) working
     end-to-end on a small in-memory example — proof the design is
     usable, not just described.

No paid subscription, no download of a large dataset, no alpha test is
performed anywhere in this script (Part 11, 18).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import (  # noqa: E402
    CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED,
    DATA_SOURCE_MATRIX,
    CausalTimestampPolicy,
    DatasetVersionRecord,
    EventTimestamps,
    HistoricalBarStore,
    HistoricalDataStore,
    PointInTimeViolation,
    ProvenancedObservation,
    assert_no_lookahead,
    compute_universe_version,
    find_duplicate_timestamps,
    find_out_of_order_indices,
    find_publication_time_violations,
    us_diversified_universe,
)
from src.data.source_profile import AvailabilityClass, DataProvenance, ResearchSuitability

RESEARCH_DATA_ROOT = Path("logs/research_data")


def _print_header(title: str) -> None:
    print("\n" + "=" * 100, flush=True)
    print(title, flush=True)
    print("=" * 100, flush=True)


def part_baseline() -> None:
    _print_header("PART 2 — CURRENT BASELINE (unchanged, verified against the actual store)")
    store = HistoricalDataStore(RESEARCH_DATA_ROOT)
    universe = us_diversified_universe()
    for symbol in universe.symbols:
        meta = store.load_metadata(symbol, "day")
        status = "MISSING" if meta is None else f"{meta.record_count} bars, {meta.start_timestamp.date()}..{meta.end_timestamp.date()}"
        print(f"  {symbol}: {status}", flush=True)
    print(f"\n  Universe: {universe.name}  survivorship_status={universe.survivorship_bias_status}", flush=True)
    assert universe.survivorship_bias_status == CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED
    print("  Adjustment: split-adjusted, dividend-unadjusted (Phase 13's independently-verified finding, unchanged).", flush=True)
    print("  This baseline is NOT altered by this phase (Part 2's explicit instruction).", flush=True)


def part_robinhood_capability_and_matrix() -> None:
    _print_header("PART 6 — ROBINHOOD CAPABILITY AUDIT / PART 5 — DATA PROVENANCE MATRIX")
    print(f"  {len(DATA_SOURCE_MATRIX)} data sources audited (src/data/source_profile.py's DATA_SOURCE_MATRIX):\n", flush=True)
    for row in DATA_SOURCE_MATRIX:
        print(f"  --- {row.data_source} ---", flush=True)
        print(f"      field={row.field}", flush=True)
        print(f"      frequency={row.frequency}", flush=True)
        print(f"      historical_coverage={row.historical_coverage}", flush=True)
        print(f"      point_in_time={row.point_in_time}  release_timestamp_available={row.release_timestamp_available}", flush=True)
        print(f"      provenance={row.provenance.value}  availability={row.availability.value}  cost={row.cost.value}", flush=True)
        print(f"      research_suitability={row.research_suitability.value}", flush=True)
        print(f"      MAJOR CAVEAT: {row.major_caveat}", flush=True)
        print("", flush=True)


def part_architecture_demo() -> None:
    _print_header("PARTS 12-15 — ARCHITECTURE DEMONSTRATION (proof the design works, not just described)")

    # --- Part 12: store interfaces -----------------------------------------------------------
    store = HistoricalDataStore(RESEARCH_DATA_ROOT)
    print(f"  HistoricalDataStore structurally satisfies the new HistoricalBarStore Protocol: {isinstance(store, HistoricalBarStore)}", flush=True)

    # --- Part 13: timestamp model + point-in-time safety --------------------------------------
    # A get_financials-shaped observation: only period_end_date known, no filing date (Part 15's
    # own audit finding) -- this MUST be flagged unsafe under PUBLICATION_TIME policy.
    unsafe_fundamental = EventTimestamps(event_time=datetime(2021, 9, 25, tzinfo=timezone.utc))  # period end only
    as_of = datetime(2021, 10, 1, tzinfo=timezone.utc)  # a month before the real 10-K was filed
    try:
        assert_no_lookahead(unsafe_fundamental, policy=CausalTimestampPolicy.PUBLICATION_TIME, as_of=as_of)
        print("  UNEXPECTED: unsafe fundamental passed the publication-time check", flush=True)
    except PointInTimeViolation as exc:
        print(f"  CONFIRMED: a get_financials-shaped observation (event_time only, no publication_time) correctly", flush=True)
        print(f"             FAILS the publication-time safety check: {exc}", flush=True)

    # A get_sec_filing_index-shaped observation: publication_time = the real date_filed. Safe once
    # as_of reaches that date; still correctly unsafe before it.
    filing = EventTimestamps(
        event_time=datetime(2021, 9, 25, tzinfo=timezone.utc),
        publication_time=datetime(2021, 10, 29, tzinfo=timezone.utc),  # AAPL's real 10-K filing date
    )
    try:
        assert_no_lookahead(filing, policy=CausalTimestampPolicy.PUBLICATION_TIME, as_of=as_of)
        print("  UNEXPECTED: filing observation passed the check before its own filing date", flush=True)
    except PointInTimeViolation:
        print(f"  CONFIRMED: the same filing, evaluated at as_of={as_of.date()} (before its 2021-10-29 filing date), is", flush=True)
        print(f"             correctly rejected as not-yet-knowable.", flush=True)
    safe_as_of = datetime(2021, 11, 1, tzinfo=timezone.utc)
    assert_no_lookahead(filing, policy=CausalTimestampPolicy.PUBLICATION_TIME, as_of=safe_as_of)  # must not raise
    print(f"  CONFIRMED: evaluated at as_of={safe_as_of.date()} (after the real 10-29 filing date), the same filing", flush=True)
    print(f"             passes cleanly.", flush=True)

    # --- Part 15: generic quality checks -------------------------------------------------------
    t0 = datetime(2022, 1, 3, tzinfo=timezone.utc)
    ts_series = [t0, t0 + timedelta(days=1), t0 + timedelta(days=1), t0 + timedelta(days=3)]  # one duplicate
    dupes = find_duplicate_timestamps(ts_series)
    print(f"\n  find_duplicate_timestamps on a series with one deliberate duplicate: {dupes}", flush=True)

    out_of_order_series = [t0, t0 - timedelta(days=1), t0 + timedelta(days=2)]
    ooo = find_out_of_order_indices(out_of_order_series)
    print(f"  find_out_of_order_indices on a deliberately-reversed pair: {ooo}", flush=True)

    obs_batch = [unsafe_fundamental, filing]
    violations = find_publication_time_violations(obs_batch, policy=CausalTimestampPolicy.PUBLICATION_TIME, as_of=as_of)
    print(f"  find_publication_time_violations([unsafe, filing], as_of={as_of.date()}): indices flagged = {violations}", flush=True)
    print(f"  (index 0 = the unsafe fundamental with no publication_time; index 1 = the filing, not yet public at this as_of)", flush=True)

    # --- Part 14: dataset versioning -----------------------------------------------------------
    universe = us_diversified_universe()
    uv = compute_universe_version(universe)
    version_record = DatasetVersionRecord(
        source="mcp__HOOD__get_sec_filing_facts (hypothetical future integration)",
        retrieval_timestamp=datetime.now(timezone.utc),
        source_version=None,
        schema_version="v1",
        adjustment_status="as-filed",
        universe_version=uv,
        feature_version=None,
    )
    print(f"\n  compute_universe_version({universe.name}) = {uv}", flush=True)
    print(f"  DatasetVersionRecord.fingerprint() = {version_record.fingerprint()}", flush=True)

    # --- ProvenancedObservation shape demo ------------------------------------------------------
    example = ProvenancedObservation(
        key="AAPL", field="revenue", value=89498000000.0, timestamps=filing,
        provenance=DataProvenance.OBSERVED, source="mcp__HOOD__get_sec_filing_facts",
    )
    print(f"\n  Example ProvenancedObservation (the shape a future FundamentalStore would persist): {example}", flush=True)


def part_ranking_and_recommendation() -> None:
    _print_header("PART 16-17 — RANKED CANDIDATE DATA SOURCES")
    ranked = sorted(
        (row for row in DATA_SOURCE_MATRIX if row.availability != AvailabilityClass.AVAILABLE_NOW),
        key=lambda r: (
            0 if r.research_suitability == ResearchSuitability.HIGH else
            1 if r.research_suitability == ResearchSuitability.MEDIUM else
            2 if r.research_suitability == ResearchSuitability.LOW else 3,
        ),
    )
    for rank, row in enumerate(ranked, start=1):
        print(f"  {rank}. {row.data_source} -- suitability={row.research_suitability.value}, cost={row.cost.value}", flush=True)

    print("\n  RECOMMENDATION: mcp__HOOD__get_sec_filing_index / get_sec_filing_facts (SEC filings) as the next", flush=True)
    print("  data source to integrate, ranked HIGH. Rationale: it is the ONLY audited non-baseline source that is", flush=True)
    print("  simultaneously (a) HISTORICALLY_BACKFILLABLE across the existing discovery window (real filing dates", flush=True)
    print("  confirmed back to 2020), (b) genuinely POINT_IN_TIME_SAFE (date_filed is a real public SEC record,", flush=True)
    print("  unlike get_financials' period_end_date), (c) FREE, and (d) low engineering complexity (a", flush=True)
    print("  FundamentalStore/EarningsStore built on ProvenancedObservation + PUBLICATION_TIME policy is a small,", flush=True)
    print("  incremental addition to the architecture this phase already built). Per Part 17: this is chosen for", flush=True)
    print("  research value per unit of cost/complexity, not sophistication -- a clean point-in-time fundamentals", flush=True)
    print("  source beats every microstructure/intraday/options candidate audited this phase, all of which are", flush=True)
    print("  UNAVAILABLE for the 2021-2023 discovery window regardless of cost.", flush=True)


def main() -> None:
    part_baseline()
    part_robinhood_capability_and_matrix()
    part_architecture_demo()
    part_ranking_and_recommendation()
    _print_header("DONE — architecture/data audit only. No hypothesis family created, no alpha tested.")


if __name__ == "__main__":
    main()
