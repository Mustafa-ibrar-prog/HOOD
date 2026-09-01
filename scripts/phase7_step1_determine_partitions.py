#!/usr/bin/env python3
"""Phase 7, Part 1 — STEP 1: computes the DISCOVERY/DEVELOPMENT/VALIDATION/
FINAL_HOLDOUT_DATA partitions from the actual data already on disk
(reuses US_DIVERSIFIED's real 5-year daily bars fetched in Phase 5 — no
re-fetch needed) and writes them to logs/research_data/phase7_partitions.jsonl.
Every later Phase 7 script reads these same partitions rather than
recomputing (and potentially drifting from) them.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import HistoricalDataStore, us_diversified_universe  # noqa: E402
from src.research import PartitionStore, determine_lifecycle_partitions  # noqa: E402


def main() -> None:
    store = HistoricalDataStore(Path("logs/research_data"))
    universe = us_diversified_universe()
    bars = store.load(universe.symbols[0], "day")
    full_start, full_end = bars[0].timestamp.date(), bars[-1].timestamp.date()
    print(f"Actual available data range for {universe.name}: {full_start} .. {full_end} ({len(bars)} bars)", flush=True)

    discovery, development, validation, holdout = determine_lifecycle_partitions(
        universe_name=universe.name, full_start=full_start, full_end=full_end,
        source_version="phase7-v1", data_version="phase5-campaign-v1", feature_version="phase7-discovery-v1",
    )

    for p in (discovery, development, validation, holdout):
        print(f"{p.partition_type.value}: {p.start_date} .. {p.end_date}  ({(p.end_date - p.start_date).days + 1} calendar days)  dataset_id={p.dataset_id}", flush=True)

    partition_store = PartitionStore(Path("logs/research_data/phase7_partitions.jsonl"))
    for p in (discovery, development, validation, holdout):
        partition_store.record(p)
    print(f"\nWritten to logs/research_data/phase7_partitions.jsonl", flush=True)


if __name__ == "__main__":
    main()
