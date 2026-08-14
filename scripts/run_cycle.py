#!/usr/bin/env python3
"""Run one real trading cycle from recorded live HOOD responses.

This is the executable half of the manual runbook documented in
src/live_bridge.py's module docstring. The agent (only the agent can call
HOOD MCP tools — see that docstring for why) fetches the tools this cycle
needs, saves each raw response as a JSON file in a data directory using
the naming convention below, then runs this script to actually execute
src.orchestrator.run_trading_cycle() against real data.

Usage:
    python3 scripts/run_cycle.py --data-dir <dir> [--now 2026-08-14T16:32:00Z]

File naming convention inside <dir> (only files that exist are loaded —
StaticHoodClient raises a clear error naming exactly what's missing if the
orchestrator asks for something nobody fetched, rather than silently
returning empty/fabricated data):

  option_positions.json                 <- get_option_positions(account_number, nonzero=true)
  equity_quotes_<SYMBOL>.json            <- get_equity_quotes([SYMBOL])
  equity_historicals_<SYMBOL>.json       <- get_equity_historicals([SYMBOL], ...)
  option_quotes_<OPTION_ID>.json         <- get_option_quotes([OPTION_ID])
  option_historicals_<OPTION_ID>.json    <- get_option_historicals([OPTION_ID], ...)
  option_chains_<SYMBOL>.json            <- get_option_chains(underlying_symbol=SYMBOL)
  option_instruments_<KEY>.json          <- get_option_instruments(...) — KEY is whatever
                                             chain_id (or ids= string) the call used; must
                                             match what HoodMarketDataProvider/hood_sync
                                             will request (see their docstrings)

Settings come from the environment exactly like the rest of this codebase
(see .env.example) — export them, or use a real .env file, before running.

Never calls place_option_order / review_option_order / cancel_option_order
— this script only ever constructs a StaticHoodClient (read-only replay)
and calls run_trading_cycle, which itself only ever reaches a
PaperExecutionGateway while TRADING_MODE=paper.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.settings import Settings  # noqa: E402
from src.live_bridge import StaticHoodClient  # noqa: E402
from src.market.hood_provider import HoodMarketDataProvider  # noqa: E402
from src.orchestrator import run_trading_cycle  # noqa: E402

_PREFIXES = {
    "equity_quotes_": "record_equity_quotes",
    "equity_historicals_": "record_equity_historicals",
    "option_quotes_": "record_option_quotes",
    "option_historicals_": "record_option_historicals",
    "option_chains_": "record_option_chains",
    "option_instruments_": "record_option_instruments",
}


def _load_client(data_dir: Path, account_number: str | None) -> StaticHoodClient:
    client = StaticHoodClient()
    for path in sorted(data_dir.glob("*.json")):
        name = path.stem
        response = json.loads(path.read_text())

        if name == "option_positions":
            if not account_number:
                print(f"warning: {path.name} present but no account_number configured; skipping", file=sys.stderr)
                continue
            client.record_option_positions(account_number, response)
            continue

        matched = False
        for prefix, method_name in _PREFIXES.items():
            if name.startswith(prefix):
                key = name[len(prefix) :]
                getattr(client, method_name)(key, response)
                matched = True
                break

        if not matched:
            print(f"warning: unrecognized file {path.name}, skipping", file=sys.stderr)

    return client


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", required=True, type=Path, help="Directory of recorded live HOOD responses")
    parser.add_argument("--now", default=None, help="ISO8601 timestamp to use as 'now'; defaults to the real current time")
    args = parser.parse_args()

    settings = Settings.from_env()
    client = _load_client(args.data_dir, settings.account_number)
    market_data = HoodMarketDataProvider(client, settings)
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)

    report = run_trading_cycle(settings=settings, market_data=market_data, hood_client=client, now=now)

    print(f"ran={report.ran} skipped_reason={report.skipped_reason!r}")
    print(f"real_positions_synced={report.real_positions_synced} monitored_real={report.monitored_real_count}")
    print(f"monitored_paper={report.monitored_paper_count} exits={report.exits}")
    print(f"scan_candidate_count={report.scan_candidate_count} new_entries={report.new_entries}")
    if report.errors:
        print(f"errors={report.errors}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
