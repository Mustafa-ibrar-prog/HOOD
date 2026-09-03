"""Phase 22, Part 7 (Theme B/C/G) — REALIZED_OPTION_PRICE_VOLATILITY_PROXY:
OHLC-derived volatility/momentum measures. These are NEVER implied
volatility -- IV requires a pricing model and is confirmed historically
unavailable for this data source. Everything here is computed strictly
from OBSERVED open/high/low/close values, causal by construction (a
value "as of" index i uses ONLY bars[..i], never bars[i+1:]).

Deliberately framework-agnostic: every function operates on plain
parallel float lists (closes / highs / lows), not on `OptionPriceBar`
or `Bar` objects directly, so the SAME estimator can be applied to an
option contract's own OHLC (Theme C) and to its underlying's OHLC
(Theme B) without two parallel implementations. `src.options.momentum_
features` wraps a couple of these for `OptionPriceBar` callers who want
that convenience; nothing here imports it (one-directional dependency).

Every output list is index-aligned to its input (same length) and uses
None wherever the trailing window would need data before index 0 --
never padded, never wrapped around, never estimated from fewer points
than the stated window.
"""

from __future__ import annotations

import math
from typing import Sequence

from src.research.analysis import stdev


def trailing_return(closes: Sequence[float], lookback: int) -> list[float | None]:
    """out[i] = % return from closes[i-lookback] to closes[i] -- the
    backward-looking mirror of `src.options.price_history.
    future_option_return`. None for i < lookback or a non-positive base
    close (mirrors that module's undefined-%-return convention)."""
    if lookback < 1:
        raise ValueError(f"lookback must be >= 1, got {lookback}")
    out: list[float | None] = []
    for i in range(len(closes)):
        j = i - lookback
        if j < 0 or closes[j] <= 0:
            out.append(None)
            continue
        out.append((closes[i] - closes[j]) / closes[j])
    return out


def _daily_returns(closes: Sequence[float]) -> list[float | None]:
    out: list[float | None] = [None]
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        out.append((closes[i] - prev) / prev if prev > 0 else None)
    return out


def close_to_close_volatility(closes: Sequence[float], window: int) -> list[float | None]:
    """Rolling stdev of daily returns over the `window` returns ending
    at (and including) index i -- the plain realized-volatility
    estimator. None until `window` returns are available (i.e. i >=
    window, since return[0] is always None)."""
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")
    returns = _daily_returns(closes)
    out: list[float | None] = []
    for i in range(len(closes)):
        if i < window:
            out.append(None)
            continue
        window_returns = returns[i - window + 1: i + 1]
        if any(r is None for r in window_returns):
            out.append(None)
            continue
        out.append(stdev(window_returns))
    return out


def mean_abs_return(closes: Sequence[float], window: int) -> list[float | None]:
    """Rolling mean of |daily return| over the trailing `window` returns
    ending at index i -- a mean-absolute-deviation-flavored companion to
    `close_to_close_volatility`'s stdev-based estimate; the two can
    diverge under fat tails, which is itself informative."""
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    returns = _daily_returns(closes)
    out: list[float | None] = []
    for i in range(len(closes)):
        if i < window:
            out.append(None)
            continue
        window_returns = returns[i - window + 1: i + 1]
        if any(r is None for r in window_returns):
            out.append(None)
            continue
        out.append(sum(abs(r) for r in window_returns) / window)
    return out


def parkinson_volatility(highs: Sequence[float], lows: Sequence[float], window: int) -> list[float | None]:
    """The Parkinson (1980) high-low range estimator:
    sqrt( sum(ln(H_t/L_t)^2) / (4 * ln(2) * window) ) over the trailing
    `window` bars ending at index i. Uses only that bar's own H/L (no
    close needed) -- a genuinely different information source than
    close-to-close volatility. None where H<=0 or L<=0 would make the
    log undefined, or where fewer than `window` bars are available."""
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    n = len(highs)
    out: list[float | None] = []
    for i in range(n):
        if i < window - 1:
            out.append(None)
            continue
        window_slice = list(zip(highs[i - window + 1: i + 1], lows[i - window + 1: i + 1]))
        if any(h <= 0 or l <= 0 or h < l for h, l in window_slice):
            out.append(None)
            continue
        sum_sq_log_ratio = sum(math.log(h / l) ** 2 for h, l in window_slice)
        out.append(math.sqrt(sum_sq_log_ratio / (4 * math.log(2) * window)))
    return out


def true_range_proxy(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], window: int) -> list[float | None]:
    """A simple (non-Wilder-smoothed) average-true-range proxy,
    normalized by the current close so it reads as a fraction of price:
    mean(TR) over the trailing `window` true-range values ending at
    index i, divided by closes[i]. TR_t = max(H_t-L_t, |H_t-C_{t-1}|,
    |L_t-C_{t-1}|), so TR needs a prior close and is undefined at index
    0."""
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    n = len(highs)
    tr: list[float | None] = [None]
    for t in range(1, n):
        prev_close = closes[t - 1]
        tr.append(max(highs[t] - lows[t], abs(highs[t] - prev_close), abs(lows[t] - prev_close)))
    out: list[float | None] = []
    for i in range(n):
        if i < window or closes[i] <= 0:
            out.append(None)
            continue
        window_tr = tr[i - window + 1: i + 1]
        if any(v is None for v in window_tr):
            out.append(None)
            continue
        out.append((sum(window_tr) / window) / closes[i])
    return out


def volatility_ratio(short_window_values: Sequence[float | None], long_window_values: Sequence[float | None]) -> list[float | None]:
    """Elementwise short/long ratio -- the "volatility expansion/
    compression" signal: > 1 means recent (short-window) volatility
    exceeds the longer-window baseline (expansion), < 1 means
    compression. None wherever either input is None or the long-window
    value is 0."""
    if len(short_window_values) != len(long_window_values):
        raise ValueError("short_window_values and long_window_values must be the same length")
    out: list[float | None] = []
    for s, l in zip(short_window_values, long_window_values):
        if s is None or l is None or l == 0:
            out.append(None)
            continue
        out.append(s / l)
    return out


def range_expansion_ratio(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], window: int) -> list[float | None]:
    """Today's own (H-L)/C range, divided by the mean of that SAME
    ratio over the `window` bars strictly BEFORE today (i-window..i-1
    -- today is excluded from its own baseline, so a value of 1.0
    means "a perfectly typical day," not a tautology). > 1 means
    today's range is wider than the recent normal."""
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    n = len(highs)
    daily_ratio = [(highs[i] - lows[i]) / closes[i] if closes[i] > 0 else None for i in range(n)]
    out: list[float | None] = []
    for i in range(n):
        if i < window or daily_ratio[i] is None:
            out.append(None)
            continue
        baseline_window = daily_ratio[i - window: i]
        if any(v is None for v in baseline_window):
            out.append(None)
            continue
        baseline = sum(baseline_window) / window
        if baseline == 0:
            out.append(None)
            continue
        out.append(daily_ratio[i] / baseline)
    return out
