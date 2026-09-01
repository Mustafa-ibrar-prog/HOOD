#!/usr/bin/env python3
"""Phase 6, sections 2-3 — STEP 2: computes the DEVELOPMENT vs HOLDOUT
boundary from the actual walk-forward windows Phase 4/5 used, and from
the actual data available on disk. Writes the result to
logs/research_data/phase6_holdout_period.json so every later Phase 6
script reads the SAME boundary rather than each recomputing (and
potentially drifting) it.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import HistoricalDataStore, us_diversified_universe  # noqa: E402
from src.research import determine_holdout_split, generate_walk_forward_windows  # noqa: E402

TRAIN_START, DATA_END = date(2021, 9, 1), date(2026, 8, 31)


def main() -> None:
    store = HistoricalDataStore(Path("logs/research_data"))
    universe = us_diversified_universe()

    # Confirm the actual latest bar on disk for the development universe,
    # rather than assuming DATA_END is still accurate.
    latest_dates = []
    for sym in universe.symbols:
        bars = store.load(sym, "day")
        if bars:
            latest_dates.append(bars[-1].timestamp.date())
    actual_data_end = max(latest_dates) if latest_dates else DATA_END
    print(f"Actual latest bar on disk across US_DIVERSIFIED: {actual_data_end}")

    windows = generate_walk_forward_windows(start=TRAIN_START, end=DATA_END, train_days=500, validation_days=150, test_days=150, step_days=200)
    print(f"Phase 4/5 walk-forward windows used to develop/validate MR-002: {len(windows)}")
    for i, w in enumerate(windows):
        print(f"  window {i}: train {w.train_start}..{w.train_end}  val {w.validation_start}..{w.validation_end}  test {w.test_start}..{w.test_end}")

    holdout = determine_holdout_split(windows=windows, full_data_start=TRAIN_START, full_data_end=actual_data_end)
    print()
    print("HOLDOUT SPLIT (computed, not hand-picked):")
    print(f"  DEVELOPMENT PERIOD: {holdout.development_start} .. {holdout.development_end}")
    print(f"  HOLDOUT PERIOD:     {holdout.holdout_start} .. {holdout.holdout_end}")
    print(f"  rationale: {holdout.rationale}")

    holdout_days = (holdout.holdout_end - holdout.holdout_start).days + 1
    print(f"\n  Holdout span: {holdout_days} calendar days (~{round(holdout_days * 5 / 7)} trading days) — SHORT. "
          "This is disclosed honestly rather than widened after the fact: the true, never-touched tail of the "
          "already-fetched dataset is small. See scripts/phase6_step5_run_holdout.py's use of "
          "US_DIVERSIFIED_SECONDARY (an entirely separate universe never touched by any Phase 4/5 tuning) as a "
          "second, larger-sample holdout test that complements this narrow temporal one.")

    out_path = Path("logs/research_data/phase6_holdout_period.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(holdout.as_dict(), indent=2, sort_keys=True) + "\n")
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    main()
