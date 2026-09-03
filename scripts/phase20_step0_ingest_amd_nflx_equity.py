#!/usr/bin/env python3
"""Phase 20, STEP 0 — ingests real AMD/NFLX daily equity bars (fetched
via a real `get_equity_historicals` call this phase) into
`HistoricalDataStore`, exactly mirroring Phase 6's
`phase6_ingest_secondary_universe.py` pattern. Needed because Phase 20
expands the options research universe to include AMD and NFLX, and
neither had local equity OHLC data from any prior phase.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import Bar, HistoricalDataStore  # noqa: E402

RAW_FILE = sys.argv[1] if len(sys.argv) > 1 else (
    "/root/.claude/projects/-home-user-HOOD/67021e56-cbf8-5d5e-be22-fc213485bd88/tool-results/mcp-HOOD-get_equity_historicals-1788406393183.txt"
)


def main() -> None:
    store = HistoricalDataStore(Path("logs/research_data"))
    payload = json.loads(Path(RAW_FILE).read_text())
    total_symbols = 0
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
