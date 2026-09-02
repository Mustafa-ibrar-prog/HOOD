"""Phase 10, Part 5: additional forward-looking targets for the
VOLATILITY_PERSISTENCE campaign — a NEW module. Reuses Phase 2's
future_return (src.research.targets, unmodified) and Phase 9's
future_realized_volatility/future_realized_variance/
future_absolute_cumulative_return/future_max_absolute_move
(src.research.volatility_targets, unmodified) directly wherever a target
already exists rather than recomputing it; only genuinely NEW target
constructions live here.

Same "targets live in src.research, never src.features, never imported by
the live/paper path" convention as every prior targets module. Every
function returns None wherever the forward window isn't fully available
— never a guessed/truncated value.

Preregistered NEW targets (Part 5; see scripts/phase10_step1_preregister_hypotheses.py):
  - future_volatility_change: future_realized_volatility - current realized_vol(vol_window)
  - future_volatility_direction: sign of future_volatility_change
  - future_absolute_return: mean |daily return| over the horizon (distinct from both
    future_absolute_cumulative_return [a NET move] and future_max_absolute_move [a single-day max])
  - future_max_drawdown: magnitude (non-negative) of the largest peak-to-trough
    decline within the forward horizon window
  - future_risk_adjusted_return: future_return / future_realized_volatility (both same horizon)
"""

from __future__ import annotations

import math
from typing import Sequence

from src.data.bar import Bar
from src.features.volatility import RealizedVolatility
from src.research.targets import future_return
from src.research.volatility_targets import _daily_returns, future_realized_volatility


def future_volatility_change(bars: Sequence[Bar], horizon: int, *, vol_window: int = 20) -> list[float | None]:
    """(future_realized_volatility(horizon) / sqrt(horizon)) -
    realized_vol(vol_window)[i] — is volatility at i+horizon higher or
    lower than it was, right now, at i?

    The sqrt(horizon) normalization is load-bearing, not cosmetic:
    future_realized_volatility(horizon) is sqrt(SUM of `horizon` squared
    daily returns), so even under perfectly CONSTANT daily volatility it
    grows roughly proportional to sqrt(horizon) (e.g. ~4.5x larger at
    horizon=20 than at horizon=1). realized_vol(vol_window), by contrast,
    is a per-day (rolling stdev of daily returns) quantity. Subtracting
    the two directly — without dividing the cumulative term back down to
    per-day units first — would make this target spuriously POSITIVE at
    longer horizons almost regardless of any genuine change in
    volatility, a pure units-mismatch artifact rather than real
    information. Dividing by sqrt(horizon) converts
    future_realized_volatility back into an RMS PER-DAY estimate, which
    is the quantity actually comparable to realized_vol(vol_window)."""
    future_vol = future_realized_volatility(bars, horizon)
    current_vol = RealizedVolatility(vol_window).compute(bars)
    sqrt_h = math.sqrt(horizon)
    return [None if f is None or c is None else (f / sqrt_h) - c for f, c in zip(future_vol, current_vol)]


def future_volatility_direction(bars: Sequence[Bar], horizon: int, *, vol_window: int = 20) -> list[float | None]:
    """sign(future_volatility_change): +1.0 rising, -1.0 falling, 0.0
    unchanged, None if undefined."""
    change = future_volatility_change(bars, horizon, vol_window=vol_window)
    return [None if c is None else (1.0 if c > 0 else (-1.0 if c < 0 else 0.0)) for c in change]


def future_absolute_return(bars: Sequence[Bar], horizon: int) -> list[float | None]:
    """mean_{k=1..horizon} |daily_return[i+k]| — the AVERAGE single-day
    absolute move over the horizon. Distinct from
    future_absolute_cumulative_return (the NET move, which can be small
    even if daily moves were large and offsetting — see Phase 9's
    round-trip example) and from future_max_absolute_move (the single
    LARGEST day, not the average)."""
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
        out.append(sum(abs(r) for r in window) / horizon)
    return out


def future_max_drawdown(bars: Sequence[Bar], horizon: int) -> list[float | None]:
    """Magnitude (non-negative) of the largest peak-to-trough decline
    within the forward path close[i..i+horizon] (inclusive of the
    starting price as the initial peak). 0.0 if the price only ever rose.
    Reported as a MAGNITUDE (abs of the usual negative drawdown
    convention) so higher values consistently mean "more downside," which
    keeps correlation/IC sign interpretation simple (Part 14)."""
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
        path = closes[i : j + 1]
        if any(p <= 0 for p in path):
            out.append(None)
            continue
        peak = path[0]
        max_dd = 0.0
        for p in path[1:]:
            peak = max(peak, p)
            max_dd = min(max_dd, (p - peak) / peak)
        out.append(abs(max_dd))
    return out


def future_risk_adjusted_return(bars: Sequence[Bar], horizon: int) -> list[float | None]:
    """future_return(horizon) / future_realized_volatility(horizon) — a
    simple, same-horizon return-per-unit-of-realized-volatility ratio.
    None if volatility is None or exactly 0 (undefined ratio)."""
    ret = future_return(bars, horizon)
    vol = future_realized_volatility(bars, horizon)
    return [None if r is None or v is None or v == 0 else r / v for r, v in zip(ret, vol)]
