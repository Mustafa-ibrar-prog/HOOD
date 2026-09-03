#!/usr/bin/env python3
"""Phase 24, STEP 1 — prints the consolidated historical-options-data
capability and vendor audit: Phase 18's real Robinhood capability
matrix (extended with this phase's own real probes, see
src.options.historical_depth_audit), and the Part 17 vendor scorecard
(src.options.vendor_scorecard). This is a reporting script only -- it
fetches no new data (every real probe behind this report was already
made via direct MCP tool calls during this phase's development; Python
scripts in this repository have never called MCP tools directly, per
this project's established boundary) and registers no hypothesis (Part
20: no new alpha hypotheses this phase).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.options.historical_depth_audit import HISTORICAL_DEPTH_PROBES, POINT_IN_TIME_EXISTENCE_RECONCILIATION, extended_capability_matrix, historical_depth_lower_bound  # noqa: E402
from src.options.vendor_scorecard import VENDOR_SCORECARD, rows_by_classification  # noqa: E402


def main() -> None:
    print(f"{'=' * 100}\nROBINHOOD CAPABILITY MATRIX (Phase 18 real probes + Phase 24 extensions)\n{'=' * 100}", flush=True)
    for row in extended_capability_matrix():
        print(f"\n[{row.capability.value}] {row.data_field}", flush=True)
        print(f"  depth   : {row.historical_depth}", flush=True)
        print(f"  evidence: {row.evidence}", flush=True)
        print(f"  caveat  : {row.major_caveat}", flush=True)

    print(f"\n{'=' * 100}\nHISTORICAL DEPTH PROBES (this phase, real)\n{'=' * 100}", flush=True)
    for probe in HISTORICAL_DEPTH_PROBES:
        print(f"  {probe.underlying_symbol} @ {probe.expiration_date_tested}: "
              f"{'FOUND' if probe.contracts_found else 'EMPTY'} -- {probe.note}", flush=True)
    print(f"\n  Confirmed lower bound (this phase's probes): {historical_depth_lower_bound()}", flush=True)
    print(f"\n  {POINT_IN_TIME_EXISTENCE_RECONCILIATION}", flush=True)

    print(f"\n{'=' * 100}\nVENDOR SCORECARD (Part 17)\n{'=' * 100}", flush=True)
    for row in VENDOR_SCORECARD:
        print(f"\n{row.source}  [{row.overall_classification.value}]  ({row.verification_level.value})", flush=True)
        print(f"  depth: {row.historical_depth}", flush=True)
        print(f"  bid/ask={row.bid_ask}  OI={row.open_interest}  IV={row.iv}  greeks={row.greeks}  "
              f"expired_contracts={row.expired_contracts}  historical_chain={row.historical_chain}  pit_capable={row.pit_capable}", flush=True)
        print(f"  cost: {row.cost}", flush=True)
        print(f"  notes: {row.notes}", flush=True)

    print(f"\n{'=' * 100}\nCLASSIFICATION COUNTS\n{'=' * 100}", flush=True)
    for classification, sources in rows_by_classification().items():
        print(f"  {classification.value}: {sources}", flush=True)

    print("\nSTEP 1 COMPLETE — audit report only. No new alpha hypothesis registered. No data purchased. "
          "No large dataset downloaded. No strategy created. No order placed.", flush=True)


if __name__ == "__main__":
    main()
