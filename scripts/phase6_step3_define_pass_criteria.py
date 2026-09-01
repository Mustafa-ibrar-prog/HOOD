#!/usr/bin/env python3
"""Phase 6, section 18 — STEP 3: writes the pre-registered pass criteria
to disk BEFORE any holdout backtest has been run. This script must run
(and its output file must exist, with a timestamp) strictly before
scripts/phase6_step5_run_holdout.py touches any holdout-period bar. The
thresholds are default values from src.research.pass_criteria, chosen
using this codebase's pre-existing conventions (MIN_OOS_TRADES_FOR_A_VERDICT,
"viable" == positive net P&L) — not reverse-engineered from any result,
because at the moment this script runs no holdout result exists yet.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.research import HoldoutPassCriteria  # noqa: E402


def main() -> None:
    out_path = Path("logs/research_data/phase6_pass_criteria.json")
    if out_path.exists():
        print(f"{out_path} already exists — pass criteria were already pre-registered. Refusing to overwrite "
              "(that would defeat the point of pre-registration). Printing the existing file instead.\n")
        print(out_path.read_text())
        return

    criteria = HoldoutPassCriteria(pre_registered_at=datetime.now(timezone.utc))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(criteria.as_dict(), indent=2, sort_keys=True) + "\n")

    print("PRE-REGISTERED HOLDOUT PASS CRITERIA (defined BEFORE any holdout backtest ran)")
    print(json.dumps(criteria.as_dict(), indent=2, sort_keys=True))
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    main()
