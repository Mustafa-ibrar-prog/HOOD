"""READ-ONLY smoke test for the direct Coinbase BTC-USD feed
(CoinbaseBtcQuoteSource, src/polymarket/btc_coinbase_source.py).
Confirms this machine can actually reach Coinbase's public, unauthenticated
candles endpoint and fetches real, recent 1-minute candles. Nothing else.

Does NOT:
  - place any Polymarket order (never imports client.py/us_client.py)
  - enable dynamic exits (never imports exit_manager.py)
  - enable live auto execution (never touches trading mode or settings)
  - read or print any secret (this Coinbase endpoint needs no API key/
    credential, and none is read from .env or the environment here)

Usage:
    python scripts/btc_feed_smoke_test.py [--limit N] [--max-age SECONDS]

Exit code: 0 if the feed is FRESH, 1 if STALE or UNAVAILABLE (including
a network/transport failure reaching Coinbase).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.polymarket.btc_coinbase_source import CoinbaseBtcQuoteSource, CoinbaseBtcQuoteSourceError  # noqa: E402
from src.polymarket.btc_market_data import compute_feed_status  # noqa: E402

# Matches POLYMARKET_BTC_MAX_BAR_AGE_SECONDS's own default in
# src/polymarket/settings.py -- kept as a literal here (not read from
# PolymarketSettings/.env) so this read-only network smoke test never
# touches real config or credentials at all.
DEFAULT_MAX_BAR_AGE_SECONDS = 300.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5, help="how many recent 1-minute candles to fetch (default: 5)")
    parser.add_argument(
        "--max-age", type=float, default=DEFAULT_MAX_BAR_AGE_SECONDS,
        help=f"seconds before the newest candle counts as STALE (default: {DEFAULT_MAX_BAR_AGE_SECONDS:.0f})",
    )
    args = parser.parse_args()

    source = CoinbaseBtcQuoteSource()
    print(f"Fetching the {args.limit} most recent BTC-USD 1-minute candle(s) from Coinbase ({source.name})...")

    try:
        bars = source.get_recent_candles(limit=args.limit)
    except CoinbaseBtcQuoteSourceError as exc:
        print(f"Could not reach/parse Coinbase's candles endpoint: {exc}")
        print("feed_status=UNAVAILABLE")
        return 1

    status = compute_feed_status(bars, max_bar_age_seconds=args.max_age, source=source.name)

    if not bars:
        print("Coinbase reachable, but returned zero candles.")
        print(f"feed_status={status.status}")
        return 1

    newest = bars[-1]
    print(f"newest_candle_time = {newest.start_time.isoformat()}")
    print(f"open={newest.open} high={newest.high} low={newest.low} close={newest.close}")
    print(f"volume = {newest.volume}")
    print(f"age_seconds = {status.bar_age_seconds:.1f}")
    print(f"feed_status = {status.status}")

    return 0 if status.status == "FRESH" else 1


if __name__ == "__main__":
    raise SystemExit(main())
