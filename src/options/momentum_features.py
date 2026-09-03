"""Phase 22, Part 4 (Theme C) — the option contract's OWN price
behavior: momentum, acceleration, gap, trend persistence, and range
expansion, computed strictly from that contract's own observed OHLC
bars. Distinct from Theme B (which uses the UNDERLYING's price
behavior) and Theme A (which compares the two) -- everything here asks
only "what has this specific option contract's own price been doing,"
independent of its underlying.

Every function is causal and index-aligned to `bars`, mirroring
`src.options.price_history`'s convention exactly (which this module
extends, not duplicates -- `daily_return_series`/`OptionPriceBar` are
imported, not reimplemented).
"""

from __future__ import annotations

from src.options.price_history import OptionPriceBar, daily_return_series
from src.options.price_volatility_proxy import range_expansion_ratio, trailing_return


def trailing_option_return(bars: list[OptionPriceBar], lookback_bars: int) -> list[float | None]:
    """Part 4 Theme C 'option return momentum': the backward-looking
    mirror of `src.options.price_history.future_option_return` -- out[i]
    is the % return from bars[i-lookback_bars].close to bars[i].close.
    A thin, `OptionPriceBar`-typed wrapper over
    `src.options.price_volatility_proxy.trailing_return` (reused, not
    duplicated)."""
    return trailing_return([b.close for b in bars], lookback_bars)


def option_return_acceleration(bars: list[OptionPriceBar]) -> list[float | None]:
    """Part 4 Theme C 'option price acceleration': the change in the
    option's own 1-day return from the prior day to today --
    out[i] = daily_return[i] - daily_return[i-1]. None wherever either
    side is undefined (the first two bars, or a $0 prior close)."""
    daily = daily_return_series(bars)
    out: list[float | None] = [None]
    for i in range(1, len(bars)):
        if daily[i] is None or daily[i - 1] is None:
            out.append(None)
            continue
        out.append(daily[i] - daily[i - 1])
    return out


def option_gap(bars: list[OptionPriceBar]) -> list[float | None]:
    """Part 4 Theme C 'option gap behavior': today's open vs. yesterday's
    close, as a % -- out[i] = (bars[i].open - bars[i-1].close) /
    bars[i-1].close. None for bars[0] (no prior close) or a $0 prior
    close."""
    out: list[float | None] = [None]
    for i in range(1, len(bars)):
        prev_close = bars[i - 1].close
        if prev_close <= 0:
            out.append(None)
            continue
        out.append((bars[i].open - prev_close) / prev_close)
    return out


def trend_persistence(bars: list[OptionPriceBar], window: int) -> list[float | None]:
    """Part 4 Theme C 'option trend persistence': the fraction of the
    trailing `window` daily returns ending at index i that were
    positive (an up-day). None until `window` non-None returns are
    available (i.e. i >= window, since return[0] is always None)."""
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    daily = daily_return_series(bars)
    out: list[float | None] = []
    for i in range(len(bars)):
        if i < window:
            out.append(None)
            continue
        window_returns = daily[i - window + 1: i + 1]
        if any(r is None for r in window_returns):
            out.append(None)
            continue
        out.append(sum(1 for r in window_returns if r > 0) / window)
    return out


def option_range_expansion(bars: list[OptionPriceBar], window: int) -> list[float | None]:
    """Part 4 Theme C 'option range expansion/compression': today's own
    (high-low)/close ratio relative to the mean of that same ratio over
    the `window` bars strictly BEFORE today. A thin wrapper over
    `src.options.price_volatility_proxy.range_expansion_ratio`."""
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    return range_expansion_ratio(highs, lows, closes, window)
