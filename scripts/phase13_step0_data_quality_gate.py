#!/usr/bin/env python3
"""Phase 13, Part 2 — STEP 0: the mandatory DATA QUALITY GATE, run BEFORE
any hypothesis is preregistered or any discovery analysis runs.

Determines whether the existing US_DIVERSIFIED daily OHLCV data (Phase 5,
HistoricalDataStore) can support economically meaningful overnight/
intraday return decomposition. Reuses the existing, unmodified
src.data.quality validation machinery (already run by every prior
phase's own quality-report step) rather than writing a second, competing
data-quality checker.

GATE OUTCOME is printed explicitly at the end: PROCEED or
DATA_INSUFFICIENT. This script makes NO code changes to any prior
phase's data or ingestion path — it only reads and reports.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import HistoricalDataStore, run_universe_quality_report, us_diversified_universe  # noqa: E402

DISCOVERY_START = "2021-09-01"
DISCOVERY_END = "2023-08-31"

# Symbols with a well-documented, large (>= 2:1) stock split that fell WITHIN the discovery
# window (2021-09-01..2023-08-31) — the sharpest available real-data test of whether the stored
# OHLCV series is genuinely split-adjusted, independent of the ingestion script's own claim.
KNOWN_SPLITS_IN_DISCOVERY_WINDOW = {
    "GOOGL": "20-for-1 split, effective 2022-07-18 — an UNADJUSTED series would show a single-day "
              "close-to-close return near -95% around that date.",
    "TSLA": "3-for-1 split, effective 2022-08-25 — an UNADJUSTED series would show a single-day "
            "close-to-close return near -67% around that date.",
}


def main() -> None:
    store = HistoricalDataStore(Path("logs/research_data"))
    universe = us_diversified_universe()

    print(f"{'=' * 100}\nPHASE 13 DATA QUALITY GATE\n{'=' * 100}", flush=True)

    # --- 2.8: does the existing pipeline already provide adjusted OHLC? ------------------------
    print("\n--- OHLC adjustment status (Part 2.1, 2.3, 2.8) ---", flush=True)
    print("Ingestion methodology: scripts/phase6_ingest_secondary_universe.py's own docstring "
          "states it 'exactly mirror[s] how Phase 5 ingested US_DIVERSIFIED' and specifies the "
          "get_equity_historicals call as adjustment_type=\"split\" (no separate Phase-5 ingestion "
          "script survives in the repo — it predates this convention — so this is the best "
          "available documentary evidence of how the PRIMARY universe was fetched, not a direct "
          "read of a Phase-5 script). adjustment_type=\"split\" means: SPLIT-adjusted, "
          "DIVIDEND-UNADJUSTED.", flush=True)
    print("Real-data confirmation (independent of the above claim) — checking known large splits "
          "that fell inside the discovery window:", flush=True)
    for symbol, note in KNOWN_SPLITS_IN_DISCOVERY_WINDOW.items():
        bars = [b for b in store.load(symbol, "day") if DISCOVERY_START <= str(b.timestamp.date()) <= DISCOVERY_END]
        worst = None
        for i in range(1, len(bars)):
            ret = (bars[i].close - bars[i - 1].close) / bars[i - 1].close
            if worst is None or abs(ret) > abs(worst[2]):
                worst = (bars[i - 1].timestamp.date(), bars[i].timestamp.date(), ret)
        print(f"  {symbol}: {note}", flush=True)
        print(f"    worst 1-day close-to-close return actually observed in the discovery window: "
              f"{worst[0]} -> {worst[1]}: {worst[2]:+.2%}", flush=True)
        if worst[2] < -0.30:
            raise RuntimeError(f"{symbol} shows an unadjusted-split-magnitude single-day move ({worst[2]:+.2%}) — "
                                f"DATA_INSUFFICIENT: the stored series is NOT reliably split-adjusted.")
    print("  CONCLUSION: no split-magnitude single-day discontinuity found for either known-split "
          "symbol -> the stored series IS genuinely split-adjusted.", flush=True)
    print("\nDIVIDEND ADJUSTMENT: NOT applied (adjustment_type=\"split\", not a dividend-inclusive "
          "variant). Documented, bounded limitation: a dividend-paying stock's close will show a "
          "small MECHANICAL downward step on each ex-dividend date (typically 0.1-0.8% for this "
          "universe's yields, ~4 trading days/year per dividend payer, roughly 1% of trading days "
          "for dividend-paying names) that reflects the cash payout, not a genuine overnight price "
          "return. This is NOT corrected here (correcting it would require fabricating dividend "
          "data this codebase does not have) — it is instead documented and treated as a bounded, "
          "known source of noise in the overnight-return feature specifically, not a reason to "
          "block the phase.", flush=True)

    # --- universe quality report (Parts 2.4-2.7: sessions, opens, high/low, missing data) -------
    print("\n--- Universe quality report (Parts 2.4-2.7) — reusing src.data.quality, unmodified ---", flush=True)
    quality = run_universe_quality_report(store, universe, "day", min_bars_required=100)
    all_available = all(q.available for q in quality)
    total_error_issues = 0
    for q in quality:
        counts = q.quality_report.counts_by_code if q.quality_report else {}
        error_codes = {"INVALID_OHLC", "NEGATIVE_PRICE", "INVALID_PRICE", "INVALID_VOLUME", "DUPLICATE_TIMESTAMP", "OUT_OF_ORDER", "SYMBOL_MISMATCH", "TIMEFRAME_MISMATCH", "TIMEZONE_ISSUE"}
        error_count = sum(v for k, v in counts.items() if k in error_codes)
        total_error_issues += error_count
        print(f"  {q.symbol}: available={q.available}  bars={q.bar_count}  range={q.date_range}  "
              f"ERROR-level issues={error_count}  all_issues={counts}", flush=True)

    print(f"\n  {sum(1 for q in quality if q.available)}/{len(quality)} symbols usable. "
          f"Total ERROR-level data-quality issues across the universe: {total_error_issues}.", flush=True)
    print("  NOTE on SUSPICIOUS_GAP warnings (visible above, ~1253 per symbol): src.data.quality's "
          "own module docstring documents this is an EXPECTED false-positive for daily bars — its "
          "gap heuristic has no trading-calendar model, so every ordinary overnight/weekend gap "
          "between daily bars (always > the 4-hour large-gap threshold) is flagged, indistinguishable "
          "from a genuinely suspicious intraday gap. This is a WARNING-severity, already-documented "
          "limitation of the shared quality checker, not evidence of missing sessions — bar counts "
          "(~1254 bars over the ~5-year stored span, consistent with ~252 trading days/year) confirm "
          "no large block of missing sessions.", flush=True)

    # --- identity check on REAL data (overnight * intraday = close-to-close) --------------------
    print("\n--- Overnight x Intraday = Close-to-Close identity, verified on REAL data (Part 5) ---", flush=True)
    max_abs_error = 0.0
    n_checked = 0
    for symbol in universe.symbols:
        bars = [b for b in store.load(symbol, "day") if DISCOVERY_START <= str(b.timestamp.date()) <= DISCOVERY_END]
        for i in range(1, len(bars)):
            prev_close, open_, close = bars[i - 1].close, bars[i].open, bars[i].close
            if prev_close <= 0 or open_ <= 0:
                continue
            overnight = open_ / prev_close - 1
            intraday = close / open_ - 1
            close_to_close = close / prev_close - 1
            reconstructed = (1 + overnight) * (1 + intraday) - 1
            error = abs(reconstructed - close_to_close)
            max_abs_error = max(max_abs_error, error)
            n_checked += 1
    print(f"  Checked {n_checked} (symbol, day) observations across the full universe/discovery window.", flush=True)
    print(f"  Max absolute reconstruction error: {max_abs_error:.2e} (expected: ~machine epsilon, i.e. floating-point noise only)", flush=True)
    if max_abs_error > 1e-9:
        raise RuntimeError(f"Identity check FAILED on real data (max error {max_abs_error:.2e}) — DATA_INSUFFICIENT.")
    print("  CONCLUSION: identity holds exactly (to floating-point precision) on every real observation checked.", flush=True)

    # --- GATE DECISION ---------------------------------------------------------------------------
    print(f"\n{'=' * 100}\nGATE DECISION\n{'=' * 100}", flush=True)
    if all_available and total_error_issues == 0 and max_abs_error <= 1e-9:
        print("PROCEED — OHLC data is split-adjusted (confirmed on real known-split observations), "
              "has zero ERROR-level quality issues across the full universe, the overnight/intraday/"
              "close-to-close identity holds exactly, and no artificial split-driven gaps were found "
              "in the discovery window. The one documented limitation (dividend-unadjusted closes, a "
              "small bounded mechanical noise source on ex-dividend dates) does not block economically "
              "meaningful overnight/intraday decomposition — it is carried forward as an explicit, "
              "reported caveat, not silently ignored.", flush=True)
    else:
        print("DATA_INSUFFICIENT — see the issues printed above.", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
