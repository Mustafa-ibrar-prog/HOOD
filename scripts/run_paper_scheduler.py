#!/usr/bin/env python3
"""Phase 41 — start the automatic market-open paper-trading scheduler.

PAPER TRADING ONLY. This script never places, modifies, or cancels a real
Robinhood order — it only drives `src.paper_trading.scheduler.
run_scheduler_forever`, which itself only ever reaches
`src.paper_trading.cycle_runner.execute_paper_cycle` ->
`src.paper_trading.engine.run_paper_experiment_cycle` (Phase 40,
UNCHANGED), the same paper-only call graph
`tests/test_phase40_safety.py` already verifies and
`tests/test_phase41_safety.py` verifies again for every new Phase 41 file.

WHAT THIS AUTOMATES: deciding WHEN a cycle is due (real US market-open
detection, configurable intraday cadence, weekday/holiday awareness),
waiting for real Robinhood data to arrive in a per-cycle inbox directory,
running the cycle the instant that data is ready, and repeating this
indefinitely without a human re-issuing "RUN" each time.

WHAT THIS DOES NOT AUTOMATE, AND WHY: nothing in this codebase can call a
HOOD MCP tool from Python (see `src/live_bridge.py`'s module docstring —
unchanged). The real, read-only Robinhood tool responses this scheduler
consumes each cycle must still be fetched by an agent and written into
the scheduler's inbox directory using the SAME naming convention
`src.live_bridge.save_hood_response_to_data_dir` already established,
followed by `src.paper_trading.data_acquisition.mark_inbox_slot_ready`.
This script does not pretend otherwise — see
`src/paper_trading/data_acquisition.py`'s module docstring for the exact
mechanics, and `docs/phase41_automatic_scheduler.md` for the full
operational runbook.

Usage:
    python3 scripts/run_paper_scheduler.py --experiment-id <id> \\
        [--cadence-minutes 15] [--data-timeout-seconds 600] \\
        [--poll-interval-seconds 30] [--inbox-root <dir>] \\
        [--slippage-tier BASELINE]

Cadence/timeouts default to the environment
(PAPER_SCHEDULER_CADENCE_MINUTES / PAPER_SCHEDULER_DATA_TIMEOUT_SECONDS /
PAPER_SCHEDULER_POLL_INTERVAL_SECONDS) when a CLI flag is not given — see
`SchedulerConfig.from_env`. Runs until the experiment reaches COMPLETED
(the configured 14-calendar-day minimum duration) or ABORTED, or the
process is stopped (Ctrl-C / SIGTERM).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paper_trading.scheduler import SchedulerConfig, run_scheduler_forever  # noqa: E402
from src.paper_trading.slippage import SlippageAssumptionTier  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--cadence-minutes", type=int, default=None, help="Overrides PAPER_SCHEDULER_CADENCE_MINUTES")
    parser.add_argument("--data-timeout-seconds", type=float, default=None, help="Overrides PAPER_SCHEDULER_DATA_TIMEOUT_SECONDS")
    parser.add_argument("--poll-interval-seconds", type=float, default=None, help="Overrides PAPER_SCHEDULER_POLL_INTERVAL_SECONDS")
    parser.add_argument("--inbox-root", type=Path, default=None, help="Defaults to logs/paper_experiments/<experiment-id>/scheduler/inbox")
    parser.add_argument("--slippage-tier", default="BASELINE", choices=["BASELINE", "STRESSED"])
    args = parser.parse_args()

    overrides: dict = {"slippage_tier": SlippageAssumptionTier(args.slippage_tier)}
    if args.cadence_minutes is not None:
        overrides["cadence_minutes"] = args.cadence_minutes
    if args.data_timeout_seconds is not None:
        overrides["data_acquisition_timeout_seconds"] = args.data_timeout_seconds
    if args.poll_interval_seconds is not None:
        overrides["poll_interval_seconds"] = args.poll_interval_seconds
    if args.inbox_root is not None:
        overrides["inbox_root"] = args.inbox_root

    config = SchedulerConfig.from_env(args.experiment_id, **overrides)

    print("PAPER TRADING ONLY. This scheduler never places, modifies, or cancels a real Robinhood order.")
    print(f"experiment_id={config.experiment_id}")
    print(f"cadence_minutes={config.cadence_minutes}")
    print(f"data_acquisition_timeout_seconds={config.data_acquisition_timeout_seconds}")
    print(f"poll_interval_seconds={config.poll_interval_seconds}")
    print(f"inbox_root={config.resolved_inbox_root()}")
    print("Waiting for real market data to arrive in the inbox at market open. Ctrl-C to stop.")

    run_scheduler_forever(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
