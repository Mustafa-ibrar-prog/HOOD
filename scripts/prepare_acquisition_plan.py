#!/usr/bin/env python3
"""Phase 42 — Process A's planning helper.

Computes (never fetches) what the current/next scheduled cycle needs:
the slot id, the inbox directory to write into, the 12-symbol universe,
and (given real prices already fetched this cycle) the bounded set of
exact strikes worth querying per symbol. Read src/live_bridge.py's and
docs/phase42_data_acquisition_automation_investigation.md's module
docstrings first — nothing in this codebase can call a HOOD MCP tool,
this script only removes the error-prone arithmetic around that
unavoidable agent-mediated step.

Usage:
    # Stage 1 -- what slot is due right now, and where does its data go?
    python3 scripts/prepare_acquisition_plan.py identity \\
        --experiment-id exp-20260908T183001Z-21ca70b3 [--cadence-minutes 15] [--now ISO8601]

    # Stage 2 -- given a real fetched price, which exact strikes to query?
    python3 scripts/prepare_acquisition_plan.py strikes --symbol GOOGL --price 332.95 \\
        [--moneyness-band 0.20] [--max-strikes 6] [--strike-increment 5.0]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.settings import Settings  # noqa: E402
from src.paper_trading.acquisition_planning import compute_cycle_identity  # noqa: E402
from src.paper_trading.near_the_money import compute_target_strikes  # noqa: E402


def cmd_identity(args: argparse.Namespace) -> int:
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
    settings = Settings.from_env()
    identity = compute_cycle_identity(
        now=now, settings=settings, experiment_id=args.experiment_id, cadence_minutes=args.cadence_minutes,
    )
    print(json.dumps({
        "now": identity.now.isoformat(),
        "market_open": identity.market_open,
        "slot_id": identity.slot_id,
        "inbox_slot_dir": str(identity.inbox_slot_dir),
        "universe": list(identity.universe),
        "n_symbols": len(identity.universe),
    }, indent=2))
    return 0


def cmd_strikes(args: argparse.Namespace) -> int:
    plan = compute_target_strikes(
        args.price, strike_increment=args.strike_increment, moneyness_band=args.moneyness_band, max_strikes=args.max_strikes,
    )
    print(json.dumps({
        "symbol": args.symbol,
        "underlying_price": plan.underlying_price,
        "strike_increment": plan.strike_increment,
        "moneyness_band": plan.moneyness_band,
        "strikes": list(plan.strikes),
    }, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_identity = sub.add_parser("identity")
    p_identity.add_argument("--experiment-id", required=True)
    p_identity.add_argument("--cadence-minutes", type=int, default=15)
    p_identity.add_argument("--now", default=None)
    p_identity.set_defaults(func=cmd_identity)

    p_strikes = sub.add_parser("strikes")
    p_strikes.add_argument("--symbol", required=True)
    p_strikes.add_argument("--price", type=float, required=True)
    p_strikes.add_argument("--strike-increment", type=float, default=None)
    p_strikes.add_argument("--moneyness-band", type=float, default=0.20)
    p_strikes.add_argument("--max-strikes", type=int, default=6)
    p_strikes.set_defaults(func=cmd_strikes)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
