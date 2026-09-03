#!/usr/bin/env python3
"""Phase 27, STEP 1 — ingests Phase 26's real data PLUS Phase 27's newly
fetched real data (combined, deterministically merged), and prints the
full expansion report: coverage matrix, concentration, corporate-action
investigation, PIT/quality checks, and the combined dataset fingerprint.

Run scripts/phase26_step0_fetch_actual_sample.py and
scripts/phase27_step0_fetch_expansion_sample.py first.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.options.phase26_ingest import RAW_EXTRACTED_DIR as P26_EXTRACTED  # noqa: E402
from src.options.phase26_pit_certification import (  # noqa: E402
    adversarial_future_observation_is_rejected,
    adversarial_missing_causal_timestamp_is_rejected,
)
from src.options.phase26_quality_rules import run_all_quality_checks  # noqa: E402
from src.options.phase27_concentration import build_concentration_report  # noqa: E402
from src.options.phase27_coverage_report import (  # noqa: E402
    BONUS_NON_TARGET_UNDERLYINGS,
    TARGET_UNDERLYINGS,
    TARGET_YEARS,
    moneyness_bucket,
    build_coverage_matrix,
    build_field_availability_report,
)
from src.options.phase27_corporate_actions import find_split_boundary_discontinuities  # noqa: E402
from src.options.phase27_fingerprint import compute_combined_fingerprint  # noqa: E402
from src.options.phase27_ingest import PHASE27_RAW_EXTRACTED_DIR as P27_EXTRACTED  # noqa: E402
from src.options.phase27_ingest import build_expanded_store_from_directories  # noqa: E402

TODAY = date(2026, 9, 3)
P26_ZIPS = P26_EXTRACTED.parent / "zips"
P27_ZIPS = P27_EXTRACTED.parent / "zips"


def main() -> None:
    retrieval_ts = datetime.now(timezone.utc)

    print("=" * 100, "\nINGESTING PHASE 26 + PHASE 27 REAL DATA (merged, deduplicated, conflict-checked)\n", "=" * 100, sep="", flush=True)
    store, conflicts = build_expanded_store_from_directories(
        quote_dirs=[
            P26_EXTRACTED / "aapl_2014_quote", P26_EXTRACTED / "aapl_2015_quote", P26_EXTRACTED / "spy_20230803_quote",
            P27_EXTRACTED / "foxa_2013_quote", P27_EXTRACTED / "goog_2015_quote", P27_EXTRACTED / "nwsa_2013_quote", P27_EXTRACTED / "twx_2014_quote",
            P27_EXTRACTED / "goog_min_20151223_quote", P27_EXTRACTED / "goog_min_20151224_quote", P27_EXTRACTED / "goog_min_20151228_quote",
            P27_EXTRACTED / "foxa_min_20130702_quote", P27_EXTRACTED / "nwsa_min_20130628_quote",
            P27_EXTRACTED / "twx_min_20140605_quote", P27_EXTRACTED / "twx_min_20140606_quote",
            P27_EXTRACTED / "aapl_min_20140606_quote", P27_EXTRACTED / "aapl_min_20140609_quote",
        ],
        trade_dirs=[
            P26_EXTRACTED / "aapl_2014_trade", P26_EXTRACTED / "aapl_2015_trade", P26_EXTRACTED / "spy_20230803_trade",
            P27_EXTRACTED / "foxa_2013_trade", P27_EXTRACTED / "goog_2015_trade", P27_EXTRACTED / "nwsa_2013_trade", P27_EXTRACTED / "twx_2014_trade",
            P27_EXTRACTED / "goog_min_20151223_trade", P27_EXTRACTED / "goog_min_20151224_trade", P27_EXTRACTED / "goog_min_20151228_trade",
            P27_EXTRACTED / "foxa_min_20130702_trade", P27_EXTRACTED / "nwsa_min_20130628_trade",
            P27_EXTRACTED / "twx_min_20140605_trade", P27_EXTRACTED / "twx_min_20140606_trade",
            P27_EXTRACTED / "aapl_min_20140606_trade", P27_EXTRACTED / "aapl_min_20140609_trade",
        ],
        oi_dirs=[
            P26_EXTRACTED / "aapl_2014_oi",
            P27_EXTRACTED / "goog_2015_oi", P27_EXTRACTED / "twx_2014_oi",
            P27_EXTRACTED / "goog_min_20151223_oi", P27_EXTRACTED / "goog_min_20151224_oi",
            P27_EXTRACTED / "twx_min_20140605_oi", P27_EXTRACTED / "twx_min_20140606_oi",
            P27_EXTRACTED / "aapl_min_20140606_oi", P27_EXTRACTED / "aapl_min_20140609_oi",
        ],
        equity_files={
            "AAPL": P26_EXTRACTED / "aapl_equity" / "aapl.csv", "SPY": P26_EXTRACTED / "spy_equity" / "spy.csv",
            "GOOG": P27_EXTRACTED / "goog_equity" / "goog.csv", "FOXA": P27_EXTRACTED / "foxa_equity" / "foxa.csv",
            "NWSA": P27_EXTRACTED / "nwsa_equity" / "nwsa.csv",
        },
        retrieval_timestamp=retrieval_ts, today=TODAY,
    )
    print(f"total contracts: {len(store.contracts)}", flush=True)
    print(f"underlyings present: {sorted(set(c.underlying_symbol for c in store.contracts.values()))}", flush=True)
    print(f"merge conflicts detected (real provider, expect 0): {len(conflicts)}", flush=True)

    print("\n" + "=" * 100 + "\nDATA QUALITY (Part 8/16)\n" + "=" * 100, flush=True)
    flags = run_all_quality_checks(store)
    counts = Counter(f.rule for f in flags)
    for rule, n in counts.items():
        print(f"  {rule}: {n}", flush=True)
    critical = [f for f in flags if f.severity == "critical"]
    print(f"  TOTAL critical flags: {len(critical)}", flush=True)
    for f in critical[:20]:
        print(f"    CRITICAL: {f}", flush=True)

    print("\n" + "=" * 100 + "\nPIT ADVERSARIAL TESTS (Part 9)\n" + "=" * 100, flush=True)
    print(f"  future observation rejected: {adversarial_future_observation_is_rejected(as_of=datetime(2015,6,1), future_event_time=datetime(2015,7,1))}", flush=True)
    print(f"  missing causal timestamp rejected: {adversarial_missing_causal_timestamp_is_rejected(as_of=datetime(2015,6,1))}", flush=True)

    print("\n" + "=" * 100 + "\nCORPORATE ACTION INVESTIGATION (Part 8)\n" + "=" * 100, flush=True)
    aapl_flags = find_split_boundary_discontinuities(store, "AAPL", date(2014, 6, 9))
    print(f"  AAPL 2014-06-09 split-boundary flags: {len(aapl_flags)}", flush=True)
    if aapl_flags:
        print(f"  sample: {aapl_flags[0]}", flush=True)

    print("\n" + "=" * 100 + "\nCOVERAGE MATRIX (Part 12) -- target underlyings\n" + "=" * 100, flush=True)
    matrix = build_coverage_matrix(store)
    header = "underlying".ljust(8) + "".join(str(y).rjust(6) for y in TARGET_YEARS)
    print("  " + header, flush=True)
    for u in TARGET_UNDERLYINGS:
        row = u.ljust(8) + "".join(("REAL" if matrix.cell(u, y).value == "real_data" else "----").rjust(6) for y in TARGET_YEARS)
        print("  " + row, flush=True)
    print(f"\n  bonus (non-target) real coverage: {matrix.bonus_coverage}", flush=True)

    print("\n" + "=" * 100 + "\nFIELD AVAILABILITY (Part 12)\n" + "=" * 100, flush=True)
    for u in ["AAPL", "SPY"] + list(BONUS_NON_TARGET_UNDERLYINGS):
        rep = build_field_availability_report(store, u)
        if rep.contract_count == 0:
            continue
        print(f"  {u}: contracts={rep.contract_count} obs={rep.observation_count} expirations={rep.expiration_count} "
              f"calls={rep.call_count} puts={rep.put_count} daily={rep.has_daily_resolution} intraday={rep.has_intraday_resolution} "
              f"quote={rep.quote_available} volume={rep.volume_available} oi={rep.open_interest_available} moneyness_buckets={rep.moneyness_buckets}", flush=True)

    print("\n" + "=" * 100 + "\nCONCENTRATION (Part 13)\n" + "=" * 100, flush=True)
    conc = build_concentration_report(store, moneyness_by_underlying=lambda u, s: moneyness_bucket(
        s, sorted(o.value for o in store.underlying.get(u, []) if o.field == "close" and o.value is not None)))
    print(f"  {conc}", flush=True)

    print("\n" + "=" * 100 + "\nFINGERPRINT (Part 11)\n" + "=" * 100, flush=True)
    fp = compute_combined_fingerprint([P26_ZIPS, P27_ZIPS])
    print(f"  combined SHA-256: {fp}", flush=True)

    print("\nSTEP 1 COMPLETE — expanded real dataset built and reported. No alpha hypothesis registered. "
          "No strategy created. No order placed. No data purchased.", flush=True)


if __name__ == "__main__":
    main()
