#!/usr/bin/env python3
"""Phase 39 — run ONE real live options research observation cycle.

RESEARCH_ONLY. This script collects market data for research purposes.
It NEVER creates, submits, modifies, or cancels a broker order of any
kind, and it never touches paper-trading, position, or P&L machinery.
The output of this script is OBSERVATIONS, not TRADES.

This is the executable half of the SAME manual runbook
src/live_bridge.py's module docstring already documents for the paper
trading orchestrator (scripts/run_cycle.py) — nothing in this codebase
can call a HOOD MCP tool from Python; only the orchestrating agent's own
tool-call interface can (see src/market/hood_client.py's module
docstring). So the agent fetches the real, read-only tools this ONE
observation cycle needs, saves each raw response as a JSON file in a
data directory using the SAME naming convention run_cycle.py already
established, then runs this script to actually execute
src.research_recorder.recorder.run_observation_cycle() against that
real data. This script does not duplicate or rewrite the recorder — it
is the smallest possible controlled invocation of the already-tested
Phase 37 recorder.

Usage:
    python3 scripts/run_live_research_cycle.py --data-dir <dir> \\
        [--now 2026-09-08T14:35:00Z] [--symbols NVDA,SPY,AAPL] \\
        [--storage-dir logs/research_data/phase37] [--cycle-id cyc-...]

File naming convention inside <data-dir> — identical to
scripts/run_cycle.py (see its module docstring), because both scripts
share src.live_bridge.load_static_hood_client_from_dir:

  equity_quotes_<SYMBOL>.json            <- get_equity_quotes([SYMBOL])
  option_chains_<SYMBOL>.json            <- get_option_chains(underlying_symbol=SYMBOL)
  option_instruments_<CHAIN_ID>.json     <- get_option_instruments(chain_id=CHAIN_ID, ...) —
                                             if the real call paginated (a "next" cursor URL
                                             was returned), the agent must follow every page
                                             for real and merge every page's "instruments"
                                             list into ONE file with "next": null before
                                             recording it here. Every instrument in the merged
                                             file must be an UNMODIFIED object from a real
                                             page — this only concatenates real pages, it never
                                             fabricates or truncates silently. (StaticHoodClient
                                             keys a recorded response by chain_id alone, not by
                                             cursor, so an un-merged multi-page recording would
                                             make get_option_chain_candidates() replay page 1
                                             repeatedly instead of the full chain.)
  option_quotes_<OPTION_ID>.json         <- get_option_quotes([...]) — keyed by the FIRST
                                             instrument_id in that call's list, matching
                                             StaticHoodClient's own lookup convention.

Settings come from the environment exactly like the rest of this
codebase (see .env.example) — export them, or use the real .env, before
running.

Only ever constructs a StaticHoodClient (read-only replay of real,
agent-fetched responses) and calls run_observation_cycle, which itself
never imports src.execution.gateway or anything order-adjacent — see
tests/test_phase39_safety.py for the same static+dynamic verification
Phase 37/38 established.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.settings import Settings  # noqa: E402
from src.live_bridge import load_static_hood_client_from_dir  # noqa: E402
from src.market.hood_provider import HoodMarketDataProvider  # noqa: E402
from src.options.phase38_campaign import default_recorder_stores  # noqa: E402
from src.research_recorder.recorder import MARKET_CLOSED, run_observation_cycle  # noqa: E402
from src.research_recorder.target_universe import TARGET_UNIVERSE  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", required=True, type=Path, help="Directory of recorded real HOOD tool responses for this one cycle")
    parser.add_argument("--now", default=None, help="ISO8601 timestamp of the real moment these responses were fetched; defaults to the real current time")
    parser.add_argument("--symbols", default=None, help="Comma-separated symbol subset of the target universe; defaults to the full 12-symbol universe")
    parser.add_argument("--storage-dir", default="logs/research_data/phase37", type=Path, help="Where Phase 37's append-only research stores live (Phase 38's disclosed default convention)")
    parser.add_argument("--cycle-id", default=None, help="Reuse an existing cycle_id to make a restart of the SAME intended observation slot resume safely instead of double-recording")
    args = parser.parse_args()

    print("RESEARCH_ONLY: this run collects market data only. No order will be placed, modified, or cancelled.")

    settings = Settings.from_env()
    client = load_static_hood_client_from_dir(args.data_dir, settings.account_number)
    market_data = HoodMarketDataProvider(client, settings)
    stores = default_recorder_stores(args.storage_dir)
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
    universe = tuple(s.strip().upper() for s in args.symbols.split(",")) if args.symbols else TARGET_UNIVERSE

    result = run_observation_cycle(client=client, market=market_data, settings=settings, stores=stores, now=now, cycle_id=args.cycle_id, universe=universe)

    if result == MARKET_CLOSED:
        print(f"MARKET_CLOSED at {now.isoformat()} -- no observation was recorded (this is the correct, non-fabricating behavior, not an error).")
        return 0

    print(f"observation_cycle_id={result.observation_cycle_id}")
    print(f"started_at={result.started_at.isoformat()} finished_at={result.finished_at.isoformat()}")
    for sr in result.symbol_results:
        status = "OK" if sr.succeeded else f"FAILED ({sr.failure_reason})"
        print(f"  {sr.symbol}: {status} contracts_observed={sr.contracts_observed} duplicates={sr.duplicates_detected}")
    if result.research_signal is not None:
        print(f"research_signal: decision={result.research_signal.decision} label={result.research_signal.label} produced_signal={result.research_signal.produced_signal}")
    print(f"storage_dir={args.storage_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
