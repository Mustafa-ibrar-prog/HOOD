"""Phase 37, Part 4 — the fixed candidate observation universe.

These are OBSERVATION TARGETS, never guaranteed trades, never a strategy
universe used to place anything. If Robinhood returns no usable
option-chain data for a symbol this cycle, the recorder records that as
an explicit per-symbol failure (`recorder.py`'s `SymbolObservationResult`)
-- it is never silently dropped from this tuple or from the cycle's own
record.
"""

from __future__ import annotations

TARGET_UNIVERSE: tuple[str, ...] = (
    "NVDA", "TSLA", "SPY", "QQQ", "AAPL", "MSFT", "AMD", "AMZN", "META", "GOOGL", "NFLX", "IWM",
)
