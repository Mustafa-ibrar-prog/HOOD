#!/usr/bin/env python3
"""Replay/analysis utility over this bot's own completed-trade journal
(src/polymarket/trade_learning.py, TASK 2) -- read-only, no live data,
no network calls.

For every LOSING completed trade, reports as much as can actually be
determined from the stored record about why: (A) incorrect BTC
direction, (B) Coinbase/reference-feed divergence, (C) poor timing,
(D) a poor Polymarket entry price, (E) an execution/reconciliation
problem, or (F) exit logic. (B) is reported as "cannot be determined"
for every trade recorded before a licensed reference feed existed --
see src/polymarket/reference_divergence.py's module docstring for why
no such feed is wired in yet. Nothing here is fabricated.

Usage:
    python3 scripts/analyze_completed_trades.py [--trades-file PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.polymarket.settings import PolymarketSettings  # noqa: E402
from src.polymarket.trade_learning import (  # noqa: E402
    CompletedTradeStore,
    CompletedTradeStoreError,
    analyze_losing_trades,
    summarize_loss_causes,
)

_CAUSE_LABELS = {
    "A_btc_direction": "A: incorrect BTC direction (strategy prediction miss)",
    "B_reference_divergence": "B: Coinbase/reference-feed divergence (confirmed)",
    "B_reference_divergence_unknown": "B: Coinbase/reference-feed divergence -- CANNOT BE DETERMINED (no reference feed data recorded)",
    "C_timing": "C: poor timing (entered with little time remaining)",
    "D_entry_price": "D: poor Polymarket entry price (wide spread at entry)",
    "E_execution_reconciliation": "E: execution/reconciliation problem (not a strategy prediction miss)",
    "F_exit_logic": "F: possible exit-logic contributor (loss realized via a dynamic exit)",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trades-file", type=str, default=None, help="Override the completed-trades journal path")
    args = parser.parse_args()

    settings = PolymarketSettings.from_env()
    trades_path = Path(args.trades_file) if args.trades_file else Path(settings.completed_trades_file)

    try:
        store = CompletedTradeStore(trades_path)
        trades = store.load()
    except CompletedTradeStoreError as exc:
        print(f"ERROR: completed-trade journal at {trades_path} is corrupted or unreadable: {exc}", file=sys.stderr)
        return 1

    if not trades:
        print(f"No completed trades recorded yet at {trades_path}.")
        return 0

    losses = analyze_losing_trades(trades)
    wins = len(trades) - len(losses)
    print(f"Completed trades: {len(trades)} ({wins} non-losing, {len(losses)} losing)\n")

    if not losses:
        print("No losing trades to analyze.")
        return 0

    for analysis in losses:
        print(f"{analysis.exit_timestamp.isoformat()}  {analysis.condition_id}  pnl=${analysis.realized_pnl_usd:+.2f}")
        print(
            f"  classification={analysis.outcome_classification}  btc_direction={analysis.btc_direction}  "
            f"entry=${analysis.entry_fill_price:.4f}  exit=${analysis.exit_price:.4f}  exit_reason={analysis.exit_reason}"
        )
        print(
            f"  seconds_remaining_at_entry={analysis.seconds_remaining_at_entry}  "
            f"polymarket_bid/ask={analysis.polymarket_yes_bid}/{analysis.polymarket_yes_ask}  "
            f"coinbase_price_at_entry={analysis.coinbase_price_at_entry}  "
            f"reference_direction_at_entry={analysis.reference_direction_at_entry}"
        )
        for cause in analysis.likely_causes:
            print(f"  -> {_CAUSE_LABELS.get(cause, cause)}")
        print()

    print("=== Summary: how many losing trades each cause appears in ===")
    counts = summarize_loss_causes(losses)
    for cause, count in sorted(counts.items()):
        print(f"  {_CAUSE_LABELS.get(cause, cause)}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
