"""Phase 9, Part 2: forward-looking VOLATILITY/MAGNITUDE target
definitions — a NEW module, same "targets live in src.research, never
src.features, never imported by the live/paper path" convention as
src.research.targets (Phase 2, left completely untouched).

Every function here is named `future_*`, deliberately looks ahead (the
one place that's correct), and returns None for indices where the future
window isn't fully available yet — never a guessed/truncated value.

Preregistered target set (Part 2, fixed BEFORE any discovery analysis ran
— see scripts/phase9_step1_preregister_hypothesis.py):
  - future_realized_volatility: sqrt(sum of squared daily returns) over the horizon
  - future_realized_variance: sum of squared daily returns over the horizon (no sqrt)
  - future_absolute_cumulative_return: |close[t+h]/close[t] - 1|
  - future_max_absolute_move: max single-day |daily return| within the horizon
"""

from __future__ import annotations

from typing import Sequence

from src.data.bar import Bar


def _daily_returns(closes: Sequence[float]) -> list[float | None]:
    """return[i] = (closes[i]-closes[i-1])/closes[i-1]; None for i=0 and
    any degenerate (<=0) price."""
    out: list[float | None] = [None]
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        out.append(None if prev <= 0 else (closes[i] - prev) / prev)
    return out


def future_realized_variance(bars: Sequence[Bar], horizon: int) -> list[float | None]:
    """target[i] = sum_{k=1..horizon} daily_return[i+k]^2 — realized
    variance over the NEXT `horizon` bars starting the day after i (never
    including day i's own return). None if the full forward window isn't
    available or any daily return within it is undefined."""
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    closes = [b.close for b in bars]
    n = len(closes)
    daily = _daily_returns(closes)
    out: list[float | None] = []
    for i in range(n):
        window = daily[i + 1 : i + 1 + horizon]
        if len(window) < horizon or any(r is None for r in window):
            out.append(None)
            continue
        out.append(sum(r * r for r in window))
    return out


def future_realized_volatility(bars: Sequence[Bar], horizon: int) -> list[float | None]:
    """sqrt(future_realized_variance) — the PRIMARY preregistered target
    (Part 2)."""
    variance = future_realized_variance(bars, horizon)
    return [None if v is None else v ** 0.5 for v in variance]


def future_absolute_cumulative_return(bars: Sequence[Bar], horizon: int) -> list[float | None]:
    """|close[i+horizon]/close[i] - 1| — magnitude of the aggregate move
    over the horizon, distinct from realized variance (which sums squared
    DAILY moves and so also captures intra-window reversals realized
    variance would count as volatility but a pure cumulative measure
    would net out)."""
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
        out.append(None if c0 <= 0 else abs((c1 - c0) / c0))
    return out


def future_max_absolute_move(bars: Sequence[Bar], horizon: int) -> list[float | None]:
    """max_{k=1..horizon} |daily_return[i+k]| — the single largest
    day-over-day move within the horizon, distinct from both realized
    variance (an aggregate) and absolute cumulative return (net, over the
    whole window) — this one is about tail/spike risk specifically."""
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    closes = [b.close for b in bars]
    n = len(closes)
    daily = _daily_returns(closes)
    out: list[float | None] = []
    for i in range(n):
        window = daily[i + 1 : i + 1 + horizon]
        if len(window) < horizon or any(r is None for r in window):
            out.append(None)
            continue
        out.append(max(abs(r) for r in window))
    return out
