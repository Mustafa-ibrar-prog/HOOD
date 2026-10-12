#!/usr/bin/env python3
"""Runs the Polymarket BTC bot in PAPER mode using LIVE BTC market data
(real Coinbase candles, exactly like scripts/run_polymarket_bot.py) --
through the EXACT SAME run_cycle() decision path real/live trading
uses, with ONE guaranteed difference: this command FORCES
trading_mode="paper" in-process, regardless of what POLYMARKET_TRADING_MODE
is set to in your environment or .env file.

THIS COMMAND CAN NEVER SUBMIT A REAL ORDER. That guarantee does not
depend on you remembering to set POLYMARKET_TRADING_MODE=paper
correctly -- it is enforced here, in code, by overriding whatever
trading_mode your settings loaded with before get_execution_gateway()
ever sees it (see run_bot() in run_polymarket_bot.py: the gateway
construction branches on settings.is_live, and is_live is a property
computed from trading_mode -- once trading_mode is forced to "paper"
here, is_live is False no matter what).

Why this matters (Round F validation requirement): a trained BTC
direction model should be observed making REAL decisions against REAL,
live BTC prices and REAL current Polymarket order books -- the exact
same features, the exact same model.predict() call, the exact same
btc_model_entry_signal.assess_model_entry() edge calculation live
trading would use -- before anyone decides whether to ever flip this
to live. run_cycle() itself does not know or care whether it's being
called from this script or run_polymarket_bot.py; the only difference
is which gateway settings.is_live selects (PaperPolymarketGateway here,
always).

Usage:
    python3 scripts/run_paper_trading.py [--once] [--max-cycles N]

Same flags as run_polymarket_bot.py; see that script's own docstring
for what they do. Ctrl-C stops the loop at any time.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_polymarket_bot import run_bot  # noqa: E402
from src.polymarket.settings import PolymarketSettings, TRADING_MODE_PAPER  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    parser.add_argument("--max-cycles", type=int, default=None, help="Stop after N cycles (default: run forever)")
    args = parser.parse_args()

    settings = PolymarketSettings.from_env()
    if settings.trading_mode != TRADING_MODE_PAPER:
        print(
            f"NOTE: POLYMARKET_TRADING_MODE={settings.trading_mode!r} in your environment -- "
            "this command FORCES paper mode regardless. No real order will be submitted."
        )
    settings = dataclasses.replace(settings, trading_mode=TRADING_MODE_PAPER)
    assert settings.is_paper and not settings.is_live  # the hard guarantee this script exists to make

    print("=" * 70)
    print("PAPER TRADING -- live BTC data, live Polymarket order books, ZERO real orders.")
    print("=" * 70)
    return run_bot(settings, once=args.once, max_cycles=args.max_cycles)


if __name__ == "__main__":
    raise SystemExit(main())
