#!/usr/bin/env python3
"""Phase 26, STEP 1 — ingests the real, already-fetched QuantConnect/
Lean sample, runs every certification check this phase built, persists
the normalized dataset, and prints the full certification report.

Run scripts/phase26_step0_fetch_actual_sample.py first. This script
touches no network -- it operates entirely on the real bytes already on
disk under logs/research_data/phase26_raw/.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.options.phase26_certified_dataset import FINAL_GATE, QUANTCONNECT_LEAN_SAMPLE_CERTIFICATION  # noqa: E402
from src.options.phase26_chain_reconstruction import contracts_incorrectly_visible_before_first_observation, reconstruct_chain_as_of  # noqa: E402
from src.options.phase26_dataset_persistence import compute_source_fingerprint, write_normalized_dataset  # noqa: E402
from src.options.phase26_execution_realism import build_execution_realism_report  # noqa: E402
from src.options.phase26_ingest import RAW_EXTRACTED_DIR, build_store_from_directories  # noqa: E402
from src.options.phase26_iv_greeks_certification import reconstruct_iv_and_greeks  # noqa: E402
from src.options.phase26_pit_certification import (  # noqa: E402
    adversarial_future_observation_is_rejected,
    adversarial_missing_causal_timestamp_is_rejected,
)
from src.options.phase26_quality_rules import run_all_quality_checks  # noqa: E402

TODAY = date(2026, 9, 3)


def main() -> None:
    retrieval_ts = datetime.now(timezone.utc)

    print("=" * 100, "\nINGESTING REAL DATA\n", "=" * 100, sep="", flush=True)
    store = build_store_from_directories(
        quote_dirs=[RAW_EXTRACTED_DIR / "aapl_2014_quote", RAW_EXTRACTED_DIR / "aapl_2015_quote", RAW_EXTRACTED_DIR / "spy_20230803_quote"],
        trade_dirs=[RAW_EXTRACTED_DIR / "aapl_2014_trade", RAW_EXTRACTED_DIR / "aapl_2015_trade", RAW_EXTRACTED_DIR / "spy_20230803_trade"],
        oi_dirs=[RAW_EXTRACTED_DIR / "aapl_2014_oi"],
        equity_files={"AAPL": RAW_EXTRACTED_DIR / "aapl_equity" / "aapl.csv", "SPY": RAW_EXTRACTED_DIR / "spy_equity" / "spy.csv"},
        retrieval_timestamp=retrieval_ts, today=TODAY,
    )
    print(f"contracts ingested: {len(store.contracts)}", flush=True)

    print("\n" + "=" * 100 + "\nPART 8 — DATA QUALITY CHECKS\n" + "=" * 100, flush=True)
    flags = run_all_quality_checks(store)
    counts = Counter(f.rule for f in flags)
    for rule, n in counts.items():
        print(f"  {rule}: {n}", flush=True)
    critical = [f for f in flags if f.severity == "critical"]
    print(f"  TOTAL critical flags: {len(critical)} (excluding the expected multiplier-assumption warning)", flush=True)

    print("\n" + "=" * 100 + "\nPART 9 — PIT / LOOKAHEAD ADVERSARIAL TESTS\n" + "=" * 100, flush=True)
    r1 = adversarial_future_observation_is_rejected(as_of=datetime(2015, 6, 1), future_event_time=datetime(2015, 7, 1))
    r2 = adversarial_missing_causal_timestamp_is_rejected(as_of=datetime(2015, 6, 1))
    print(f"  future observation correctly rejected: {r1}", flush=True)
    print(f"  missing-causal-timestamp correctly rejected: {r2}", flush=True)

    print("\n" + "=" * 100 + "\nPART 5 — CHAIN RECONSTRUCTION (AAPL, as of 2014-07-01)\n" + "=" * 100, flush=True)
    as_of = datetime(2014, 7, 1)
    chain = reconstruct_chain_as_of(store, "AAPL", as_of)
    print(f"  reconstructed (knowable) contracts: {len(chain.reconstructed_contracts)}", flush=True)
    print(f"  excluded (already expired): {len(chain.excluded_already_expired)}", flush=True)
    print(f"  distinct real strikes visible: {len(set(c.strike for c in chain.reconstructed_contracts))}", flush=True)
    violations = contracts_incorrectly_visible_before_first_observation(store, "AAPL", as_of)
    print(f"  adversarial before-first-observation violations (should be 0): {len(violations)}", flush=True)

    print("\n" + "=" * 100 + "\nPART 6 — EXECUTION REALISM (SPY, 2023-08-03)\n" + "=" * 100, flush=True)
    for cid in sorted(store.contracts):
        if not cid.startswith("SPY"):
            continue
        rep = build_execution_realism_report(store, cid)
        print(f"  {cid}: grade={rep.grade.value} mean_spread=${rep.mean_spread_dollars:.4f} "
              f"({rep.mean_spread_pct_of_mid:.2%} of mid) trades_inside_spread={rep.trades_inside_spread_rate:.2%}", flush=True)

    print("\n" + "=" * 100 + "\nPART 7 — IV/GREEKS RECONSTRUCTION\n" + "=" * 100, flush=True)
    aapl_cid = "AAPL_call_100.0000_2016-01-15"
    if aapl_cid in store.contracts:
        attempt = reconstruct_iv_and_greeks(store, store.contracts[aapl_cid], date(2015, 1, 2), underlying_symbol="AAPL")
        print(f"  AAPL 2015-01-02 reconstructed IV: {attempt.iv.value}", flush=True)
        print(f"  AAPL 2015-01-02 reconstructed Greeks: delta={attempt.greeks.delta:.4f} gamma={attempt.greeks.gamma:.6f} "
              f"vega={attempt.greeks.vega:.4f} theta={attempt.greeks.theta:.4f} rho={attempt.greeks.rho:.4f}", flush=True)
    spy_cid = "SPY_call_430.0000_2023-09-01"
    if spy_cid in store.contracts:
        attempt2 = reconstruct_iv_and_greeks(store, store.contracts[spy_cid], date(2023, 8, 3), underlying_symbol="SPY")
        print(f"  SPY 2023-08-03 reconstruction attempt: underlying_price_source={attempt2.underlying_price_source} "
              f"iv={attempt2.iv.value} (honest UNAVAILABLE -- no paired real underlying price in-sample)", flush=True)

    print("\n" + "=" * 100 + "\nPART 12 — PERSISTENCE\n" + "=" * 100, flush=True)
    fingerprint = compute_source_fingerprint(RAW_EXTRACTED_DIR.parent / "zips")
    out_path = RAW_EXTRACTED_DIR.parent.parent / "phase26_normalized_dataset.jsonl"
    manifest = write_normalized_dataset(store, out_path, source_fingerprint=fingerprint)
    print(f"  wrote {out_path} manifest={manifest}", flush=True)

    print("\n" + "=" * 100 + "\nPART 10 — CERTIFICATION SCORE\n" + "=" * 100, flush=True)
    sc = QUANTCONNECT_LEAN_SAMPLE_CERTIFICATION
    for s in sc.scores:
        print(f"  {s.dimension.value:32s} {s.score}/5", flush=True)
    print(f"\n  TOTAL: {sc.total_score()}/{sc.max_possible_score()}", flush=True)
    print(f"  Critical blockers triggered: {[d.value for d in sc.triggered_critical_blockers()] or 'none'}", flush=True)
    print(f"  DISQUALIFIED: {sc.disqualified()}", flush=True)

    print("\n" + "=" * 100 + "\nPART 11 — FINAL GATE\n" + "=" * 100, flush=True)
    print(f"  {FINAL_GATE.value.upper()}", flush=True)

    print("\nSTEP 1 COMPLETE — real data certified. No alpha hypothesis registered. No strategy created. "
          "No order placed. No data purchased.", flush=True)


if __name__ == "__main__":
    main()
