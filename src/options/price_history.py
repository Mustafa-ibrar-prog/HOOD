"""Phase 19, Part 3/7 — option historical OHLC price bars and strictly
causal return computation.

`Bar` (src.data.bar) is NOT reused here: it requires `volume: int >= 0`,
and Phase 18 established (confirmed via a real probe, tool's own guide
text: "Option bars carry no volume") that historical option bars NEVER
carry a real volume figure. Recording 0 would misrepresent "not
available" as "zero contracts traded" -- a factual error, not a rounding
choice. `OptionPriceBar` below has no volume field at all.

Every return function here is index-aligned and strictly causal: a
return computed "as of" bar index i uses ONLY bars[i] and (for a forward
return) bars[i+h] where h > 0 -- never information from before the
series' start relative to i, and a forward return is None whenever
i+h would run past the end of the series (no padding, no wraparound,
no silently truncating the horizon). See tests/test_options_returns.py's
lookahead tests for the structural proof.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class OptionPriceBar:
    """One daily OHLC bar for one option contract. No volume field --
    see module docstring."""

    date: date
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise ValueError(f"OptionPriceBar.high ({self.high}) must be >= low ({self.low})")
        for name, value in (("open", self.open), ("high", self.high), ("low", self.low), ("close", self.close)):
            if value < 0:
                raise ValueError(f"OptionPriceBar.{name} must be >= 0, got {value}")


def close_series(bars: list[OptionPriceBar]) -> list[float]:
    return [b.close for b in bars]


def close_to_close_return(prev_close: float, close: float) -> float | None:
    """A single-period % return. None (never a divide-by-zero exception
    or a fabricated value) when prev_close <= 0 -- a $0.00 close is a
    real, observed state for a deep-OTM contract near expiration, not an
    error, but a % return relative to zero is undefined."""
    if prev_close <= 0:
        return None
    return (close - prev_close) / prev_close


def daily_return_series(bars: list[OptionPriceBar]) -> list[float | None]:
    """One value per bar, aligned to bars[i]: bars[0] is always None (no
    prior close exists); bars[i] for i>=1 is the close-to-close return
    from bars[i-1] to bars[i]. Length always equals len(bars)."""
    out: list[float | None] = [None]
    for i in range(1, len(bars)):
        out.append(close_to_close_return(bars[i - 1].close, bars[i].close))
    return out


def future_option_return(bars: list[OptionPriceBar], horizon_bars: int) -> list[float | None]:
    """Part 7: forward N-bar option return, causal and index-aligned.
    out[i] = % return from bars[i].close (entry) to bars[i+horizon_bars].close
    (exit) -- i.e. "if you bought this contract at bar i's close and sold
    it at bar i+horizon's close, what was the return." out[i] is None
    whenever i+horizon_bars >= len(bars) (the tail, where the horizon
    would run past the observed data -- NEVER filled by looking outside
    the series) or whenever bars[i].close <= 0 (undefined % return off a
    zero base). Length always equals len(bars)."""
    if horizon_bars < 1:
        raise ValueError(f"horizon_bars must be >= 1, got {horizon_bars}")
    n = len(bars)
    out: list[float | None] = []
    for i in range(n):
        j = i + horizon_bars
        if j >= n:
            out.append(None)
            continue
        entry = bars[i].close
        if entry <= 0:
            out.append(None)
            continue
        out.append((bars[j].close - entry) / entry)
    return out


def holding_period_return(entry_close: float, exit_close: float) -> float | None:
    """A single, explicit (entry, exit) pair's % return -- the building
    block `future_option_return` wraps for a whole series. None when
    entry_close <= 0 (undefined base), matching close_to_close_return's
    convention."""
    if entry_close <= 0:
        return None
    return (exit_close - entry_close) / entry_close


STANDARD_FORWARD_HORIZONS: tuple[int, ...] = (1, 3, 5, 10, 20)  # Part 7's preregistered horizon set, trading days
