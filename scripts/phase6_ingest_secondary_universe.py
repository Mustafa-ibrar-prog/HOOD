#!/usr/bin/env python3
"""Phase 6, section 4: ingests the real, fetched daily bar data for the
second (disjoint) universe — US_DIVERSIFIED_SECONDARY — into
HistoricalDataStore, exactly mirroring how Phase 5 ingested US_DIVERSIFIED.
Reads raw MCP get_equity_historicals response files saved to disk (too
large to hold in the orchestrating agent's context) and converts each bar
to the normalized src.data.bar.Bar shape.

REPRODUCTION NOTE: the two paths below are the exact files this ran
against in the session that first built US_DIVERSIFIED_SECONDARY — a
session-scoped tool-result cache path, not a repo artifact (the raw JSON
is not committed; see .gitignore's logs/ and *.jsonl rules, same
convention as Phase 4/5's fetched data). To reproduce this universe's
dataset from scratch: call get_equity_historicals for the 20 symbols in
src.data.universe.us_diversified_secondary_universe() (two calls of 10
symbols each; interval="day", bounds="regular", adjustment_type="split",
start_time="2021-09-01T00:00:00Z"), save each response to a file, and pass
those paths as RAW_FILES (or as argv) instead.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import Bar, HistoricalDataStore  # noqa: E402

RAW_FILES = sys.argv[1:] or [
    "/root/.claude/projects/-home-user-HOOD/67021e56-cbf8-5d5e-be22-fc213485bd88/tool-results/mcp-HOOD-get_equity_historicals-1788287589037.txt",
    "/root/.claude/projects/-home-user-HOOD/67021e56-cbf8-5d5e-be22-fc213485bd88/tool-results/mcp-HOOD-get_equity_historicals-1788287608978.txt",
]


def main() -> None:
    store = HistoricalDataStore(Path("logs/research_data"))
    total_symbols = 0
    for raw_path in RAW_FILES:
        payload = json.loads(Path(raw_path).read_text())
        for result in payload["data"]["results"]:
            symbol = result["symbol"]
            bars = []
            for h in result["bars"]:
                ts = datetime.fromisoformat(h["begins_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
                bars.append(Bar(
                    timestamp=ts, symbol=symbol, timeframe="day",
                    open=float(h["open_price"]), high=float(h["high_price"]),
                    low=float(h["low_price"]), close=float(h["close_price"]),
                    volume=int(h["volume"]), source="hood",
                ))
            bars.sort(key=lambda b: b.timestamp)
            meta = store.save(symbol, "day", bars, source="hood")
            print(f"{symbol}: {len(bars)} bars saved ({meta.start_timestamp} .. {meta.end_timestamp})")
            total_symbols += 1
    print(f"\nTotal symbols ingested: {total_symbols}")


if __name__ == "__main__":
    main()
