#!/usr/bin/env python3
"""The interim, human/agent-assisted bridge for real BTC spot data (see
src/polymarket/btc_market_data.py's module docstring for why this has
to be a bridge rather than something the bot polls itself):
mcp__HOOD__get_crypto_quotes can only be called from an agent's own
tool-call turn, never from this plain Python process. So: an agent (or
a human) calls that MCP tool itself, then runs this script with either
the resulting mark price directly, or the tool's raw JSON response, to
record ONE real sample into the persisted BTC price history that
exit_manager.py's dynamic-exit evidence engine reads from.

Until something actually runs this (repeatedly, roughly once per
desired bar), the BTC evidence engine honestly sees no/insufficient
history and the dynamic-exit cascade HOLDs — see
btc_intelligence.build_btc_momentum_evidence's docstring. This script
adds no automation and starts no background process; it records
exactly one data point per invocation, nothing more.

Usage:
    # Simplest: you already know the mark price (e.g. from
    # get_crypto_quotes's own output).
    python3 scripts/feed_btc_quote.py feed --price 67123.45

    # Or hand it the tool's raw JSON response directly (stdin or a
    # file) and let it find BTC-USD's mark price itself.
    python3 scripts/feed_btc_quote.py feed --quotes-json - --symbol BTC-USD <<< '{"results": [...]}'
    python3 scripts/feed_btc_quote.py feed --quotes-json response.json --symbol BTC-USD

    # Read-only: show what's been fed so far, aggregated into bars.
    python3 scripts/feed_btc_quote.py show --interval-seconds 60
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.polymarket.btc_market_data import BtcPriceHistoryStore, extract_mark_price  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)

    p_feed = sub.add_parser("feed", help="Record one real BTC quote sample.")
    group = p_feed.add_mutually_exclusive_group(required=True)
    group.add_argument("--price", type=float, help="The mark price directly, e.g. from get_crypto_quotes's own output.")
    group.add_argument("--quotes-json", metavar="FILE_OR_-", help="Path to a file holding get_crypto_quotes's raw JSON response, or '-' for stdin.")
    p_feed.add_argument("--symbol", default="BTC-USD", help="Only used with --quotes-json. Default: BTC-USD.")
    p_feed.add_argument("--at", default=None, help="ISO8601 timestamp for this sample. Default: now (UTC).")

    p_show = sub.add_parser("show", help="Print the bars aggregated from samples fed so far. Read-only.")
    p_show.add_argument("--interval-seconds", type=int, default=None, help="Default: POLYMARKET_BTC_BAR_INTERVAL_SECONDS.")

    args = parser.parse_args()
    settings = PolymarketSettings.from_env()
    store = BtcPriceHistoryStore(Path(settings.btc_price_history_file))

    if args.action == "feed":
        at = datetime.fromisoformat(args.at) if args.at else datetime.now(timezone.utc)
        if args.price is not None:
            price = args.price
        else:
            raw = sys.stdin.read() if args.quotes_json == "-" else Path(args.quotes_json).read_text()
            price = extract_mark_price(json.loads(raw), args.symbol)
            if price is None:
                print(f"No mark price found for {args.symbol!r} in the given response.")
                return 1
        sample = store.record_quote(price, at=at)
        print(f"Recorded {args.symbol if args.quotes_json else 'BTC'} quote: ${sample.price:.2f} @ {sample.observed_at.isoformat()}")
        print(f"-> {settings.btc_price_history_file}")
        return 0

    interval = args.interval_seconds or settings.btc_bar_interval_seconds
    bars = store.get_bars(interval_seconds=interval)
    print(f"{len(bars)} closed {interval}s bar(s) from {settings.btc_price_history_file}:")
    for bar in bars[-20:]:
        print(f"  {bar.start_time.isoformat()}  O={bar.open:.2f} H={bar.high:.2f} L={bar.low:.2f} C={bar.close:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
