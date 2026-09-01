"""Forward-looking TARGET generation — the ONLY place in this whole
codebase where deliberately looking ahead of a bar's own index is
correct and intended.

This is a hard, load-bearing separation (Phase 2, section 7): a target is
what research tries to PREDICT, never something a feature or a live
signal is allowed to see. Every function here is named `future_*` for
exactly that reason, lives in `src.research` (never `src.features`), and
is never imported by src/features/, src/strategy/, src/position_manager/,
or src/orchestrator.py — the live/paper trading path has no access to
this module at all.
"""

from __future__ import annotations

import math
from typing import Sequence

from src.data.bar import Bar


def future_return(bars: Sequence[Bar], horizon: int, *, log: bool = False) -> list[float | None]:
    """target[i] = the return from close[i] to close[i+horizon].

    The final `horizon` entries are None — at those indices the future bar
    the target needs doesn't exist yet in `bars`. That is what makes this
    a TARGET and not a feature: a feature degrading to None on missing
    *past* data is normal (not enough history); a target degrading to None
    on missing *future* data is the whole point — it is undefined until
    the future actually happens, and must never be filled in with a guess.
    """
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    closes = [b.close for b in bars]
    n = len(closes)
    out: list[float | None] = []
    for i in range(n):
        j = i + horizon
        if j >= n:
            out.append(None)
            continue
        c0, c1 = closes[i], closes[j]
        if c0 <= 0 or c1 <= 0:
            out.append(None)
        elif log:
            out.append(math.log(c1 / c0))
        else:
            out.append((c1 - c0) / c0)
    return out
