"""Phase 13, Part 6: forward-looking overnight/intraday targets — a NEW
module. next_close_to_close_return reuses Phase 2's future_return
directly (unmodified — a close-to-close return over `horizon` bars is
exactly what it already computes); only the genuinely NEW targets
(next_overnight_return, next_intraday_return) live here.

horizon=1 (the primary horizon, Part 6): the literal next session's own
overnight/intraday component.
horizon>1 (the secondary, preregistered 5-session horizon): the
CUMULATIVE sum of that component across the next `horizon` sessions — an
aggregate forward-looking overnight/intraday drift, not a single day N
sessions out (documented, not silently assumed).
"""

from __future__ import annotations

from typing import Sequence

from src.data.bar import Bar


def future_overnight_return(bars: Sequence[Bar], horizon: int) -> list[float | None]:
    """target[i] = sum_{k=1..horizon} overnight_return[i+k], where
    overnight_return[j] = Open_j/Close_{j-1} - 1. None if the full
    forward window isn't available or any overnight leg within it is
    undefined (non-positive open/close)."""
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    n = len(bars)
    overnight: list[float | None] = [None] * n
    for j in range(1, n):
        prev_close, open_ = bars[j - 1].close, bars[j].open
        if prev_close > 0 and open_ > 0:
            overnight[j] = open_ / prev_close - 1
    out: list[float | None] = []
    for i in range(n):
        window = overnight[i + 1 : i + 1 + horizon]
        if len(window) < horizon or any(v is None for v in window):
            out.append(None)
            continue
        out.append(sum(window))  # type: ignore[arg-type]
    return out


def future_intraday_return(bars: Sequence[Bar], horizon: int) -> list[float | None]:
    """target[i] = sum_{k=1..horizon} intraday_return[i+k], where
    intraday_return[j] = Close_j/Open_j - 1. None if the full forward
    window isn't available or any intraday leg within it is undefined."""
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    n = len(bars)
    intraday: list[float | None] = [None] * n
    for j in range(n):
        open_, close = bars[j].open, bars[j].close
        if open_ > 0 and close > 0:
            intraday[j] = close / open_ - 1
    out: list[float | None] = []
    for i in range(n):
        window = intraday[i + 1 : i + 1 + horizon]
        if len(window) < horizon or any(v is None for v in window):
            out.append(None)
            continue
        out.append(sum(window))  # type: ignore[arg-type]
    return out
