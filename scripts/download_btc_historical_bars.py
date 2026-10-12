#!/usr/bin/env python3
"""Downloads real historical BTC-USD 1-minute OHLCV candles from
Coinbase Exchange's public, unauthenticated candles API
(CoinbaseBtcQuoteSource.get_historical_candles — btc_coinbase_source.py)
and saves them to a local JSON file.

This is the step scripts/backtest_btc_direction_model.py's own module
docstring calls out as missing: that script can TRAIN/BACKTEST against
real bars, but has no way to fetch them itself. This script is that
missing piece — run it once (or periodically, to extend your saved
history) from an environment with real network access to
api.exchange.coinbase.com (this sandboxed development session does
NOT have that access — see btc_coinbase_source.py's module docstring;
this script was built and unit-tested against a deterministic fake
HTTP transport, never run against the real API from here).

THIS SCRIPT NEVER PLACES A POLYMARKET ORDER. It only makes read-only
HTTPS GET requests to Coinbase and writes a local JSON file.

Output format: a plain JSON array of real OHLCV bars, oldest first —
the exact shape scripts/backtest_btc_direction_model.py's --bars-file
loads directly:
    [{"start_time": "...", "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}, ...]

Re-running this with an overlapping or adjoining range is safe and
idempotent: any existing bars already saved at --output are loaded
first and merged (deduplicated by exact timestamp) with the newly
downloaded range before writing back — so you can extend your saved
dataset incrementally (e.g. a cron-style re-run once a day pulling
"yesterday through now") without ever losing or duplicating a bar.

Usage (run on a machine with real network access, e.g. your Windows
machine — see PowerShell examples in this round's final report):

    python3 scripts/download_btc_historical_bars.py \\
        --start 2026-07-01 --end 2026-10-01 \\
        --output logs/polymarket/btc_historical_bars.json

Then train/backtest against the result:

    python3 scripts/backtest_btc_direction_model.py \\
        --bars-file logs/polymarket/btc_historical_bars.json

(scripts/run_btc_model_pipeline.py chains both of these into one
command — see that script's own docstring.)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.polymarket.btc_coinbase_source import CoinbaseBtcQuoteSource, CoinbaseBtcQuoteSourceError  # noqa: E402

# Polite default delay between Coinbase chunk requests (see
# CoinbaseBtcQuoteSource.get_historical_candles's own docstring) -- a
# multi-month pull is hundreds of chunk requests; this keeps that
# request rate well under Coinbase's public, unauthenticated rate
# limit without the caller having to think about it. Override with
# --request-delay-seconds for a short range where this doesn't matter.
_DEFAULT_REQUEST_DELAY_SECONDS = 0.35


def _parse_datetime(raw: str) -> datetime:
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{raw!r} is not a valid ISO 8601 date/datetime (e.g. 2026-07-01 or 2026-07-01T00:00:00Z)"
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _bar_to_dict(bar) -> dict:
    return {
        "start_time": bar.start_time.isoformat(), "open": bar.open, "high": bar.high, "low": bar.low,
        "close": bar.close, "volume": bar.volume,
    }


def _load_existing_bars(path: Path) -> dict[datetime, dict]:
    if not path.is_file():
        return {}
    raw = path.read_text()
    if not raw.strip():
        return {}
    rows = json.loads(raw)
    return {datetime.fromisoformat(row["start_time"]): row for row in rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=_parse_datetime, required=True, help="Start of the range to download (inclusive), e.g. 2026-07-01")
    parser.add_argument("--end", type=_parse_datetime, default=None, help="End of the range to download (exclusive). Default: now.")
    parser.add_argument("--product-id", default="BTC-USD")
    parser.add_argument("--output", type=Path, default=Path("logs/polymarket/btc_historical_bars.json"))
    parser.add_argument(
        "--request-delay-seconds", type=float, default=_DEFAULT_REQUEST_DELAY_SECONDS,
        help=f"Delay between Coinbase chunk requests (default {_DEFAULT_REQUEST_DELAY_SECONDS}s -- a large pull is many chunks).",
    )
    args = parser.parse_args()

    end = args.end or datetime.now(timezone.utc)
    if args.start >= end:
        print(f"ERROR: --start ({args.start.isoformat()}) must be before --end ({end.isoformat()})", file=sys.stderr)
        return 2

    print(f"Downloading real Coinbase {args.product_id} 1-minute candles from {args.start.isoformat()} to {end.isoformat()} ...")
    expected_chunks = max(1, -(-int((end - args.start).total_seconds() // 60) // 300))
    print(f"(~{expected_chunks} request(s) at <= 300 candles each, {args.request_delay_seconds}s apart)")

    source = CoinbaseBtcQuoteSource(product_id=args.product_id)
    try:
        bars = source.get_historical_candles(start=args.start, end=end, request_delay_seconds=args.request_delay_seconds)
    except CoinbaseBtcQuoteSourceError as exc:
        print(f"ERROR: download failed partway through: {exc}", file=sys.stderr)
        print("Nothing was written -- re-run with the same --start once network access is restored; "
              "already-downloaded bars from a PRIOR successful run at --output are untouched.", file=sys.stderr)
        return 1

    print(f"Downloaded {len(bars)} real candle(s) from Coinbase.")
    if not bars:
        print("WARNING: zero candles returned for this range -- nothing to merge/save.", file=sys.stderr)
        return 0

    existing = _load_existing_bars(args.output)
    before_count = len(existing)
    for bar in bars:
        existing[bar.start_time] = _bar_to_dict(bar)
    merged = [existing[ts] for ts in sorted(existing)]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(merged, indent=2, sort_keys=True))

    added = len(existing) - before_count
    print(
        f"Saved {len(merged)} total real bar(s) to {args.output} "
        f"({before_count} already present, {added} newly added, {len(bars) - added} overlapped/overwritten)."
    )
    print(f"Range now covered: {merged[0]['start_time']} .. {merged[-1]['start_time']}")
    print(f"\nNext: python3 scripts/backtest_btc_direction_model.py --bars-file {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
