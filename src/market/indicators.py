"""Pure, dependency-free technical indicator math.

The HOOD MCP get_equity_technical_indicators tool will eventually compute
most of these server-side for the *underlying*. These local implementations
exist for two reasons:
  1. Options themselves have no equivalent indicators tool — option-side
     EMA/VWAP/structure must be computed locally from option_bars.
  2. Pure functions here are trivially unit-testable without any network
     or MCP dependency, which keeps the decision logic verifiable in CI.
"""

from __future__ import annotations

from typing import Sequence

from src.market.models import PriceBar


def ema(values: Sequence[float], period: int) -> list[float]:
    """Exponential moving average. Returns one value per input value (the
    first `period - 1` values are seeded with a simple average of what's
    available, standard EMA warm-up behavior)."""
    if period <= 0:
        raise ValueError("period must be > 0")
    if not values:
        return []

    multiplier = 2 / (period + 1)
    result: list[float] = []
    running = values[0]
    result.append(running)
    for value in values[1:]:
        running = (value - running) * multiplier + running
        result.append(running)
    return result


def rsi(values: Sequence[float], period: int = 14) -> list[float]:
    """Wilder's RSI. Returns one value per input value; the first value is
    seeded at 50 (neutral) since there's no prior bar to diff against."""
    if period <= 0:
        raise ValueError("period must be > 0")
    if not values:
        return []
    if len(values) == 1:
        return [50.0]

    gains: list[float] = [0.0]
    losses: list[float] = [0.0]
    for prev, curr in zip(values, values[1:]):
        change = curr - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    result: list[float] = [50.0]
    avg_gain = sum(gains[1 : period + 1]) / period if len(gains) > period else sum(gains[1:]) / max(len(gains) - 1, 1)
    avg_loss = sum(losses[1 : period + 1]) / period if len(losses) > period else sum(losses[1:]) / max(len(losses) - 1, 1)

    for i in range(1, len(values)):
        if i <= period:
            avg_gain = sum(gains[1 : i + 1]) / i
            avg_loss = sum(losses[1 : i + 1]) / i
        else:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            result.append(100.0 if avg_gain > 0 else 50.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100 - (100 / (1 + rs)))

    return result


def macd(
    values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float], list[float], list[float]]:
    """Returns (macd_line, signal_line, histogram), one value per input."""
    if not values:
        return [], [], []
    fast_ema = ema(values, fast)
    slow_ema = ema(values, slow)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
    signal_line = ema(macd_line, signal)
    histogram = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, histogram


def vwap(bars: Sequence[PriceBar]) -> float | None:
    """Volume-weighted average price over the given bars, using typical
    price ((H+L+C)/3) per bar. Returns None if there's no volume."""
    total_volume = sum(bar.volume for bar in bars)
    if total_volume <= 0:
        return None
    total_pv = sum(((bar.high + bar.low + bar.close) / 3) * bar.volume for bar in bars)
    return total_pv / total_volume


def higher_highs_lower_highs(bars: Sequence[PriceBar], lookback: int = 5) -> tuple[bool, bool]:
    """Returns (higher_highs, lower_highs) over the last `lookback` bars,
    comparing each bar's high to the prior bar's high in that window."""
    window = list(bars[-lookback:]) if lookback > 0 else list(bars)
    if len(window) < 2:
        return False, False

    higher = all(b.high >= a.high for a, b in zip(window, window[1:]))
    lower = all(b.high <= a.high for a, b in zip(window, window[1:]))
    made_higher = any(b.high > a.high for a, b in zip(window, window[1:]))
    made_lower = any(b.high < a.high for a, b in zip(window, window[1:]))

    return (higher and made_higher), (lower and made_lower)


def detect_breakout_continuation(
    bars: Sequence[PriceBar], resistance_lookback: int = 20, confirm_bars: int = 2
) -> bool:
    """True if price broke above the resistance formed by the
    `resistance_lookback` bars immediately preceding the most recent
    `confirm_bars`, and has closed above that resistance on every one of
    those confirming bars."""
    total_needed = resistance_lookback + confirm_bars
    if len(bars) < total_needed:
        return False

    resistance_window = bars[-total_needed:-confirm_bars]
    resistance = max(b.high for b in resistance_window)
    confirming = bars[-confirm_bars:]
    return all(b.close > resistance for b in confirming)


def detect_failed_breakout(bars: Sequence[PriceBar], resistance_lookback: int = 20) -> bool:
    """True if the second-to-last bar broke above the resistance formed by
    the `resistance_lookback` bars before it, but the most recent close has
    fallen back below that resistance."""
    total_needed = resistance_lookback + 2
    if len(bars) < total_needed:
        return False

    resistance_window = bars[-total_needed:-2]
    resistance = max(b.high for b in resistance_window)
    breakout_bar, last_bar = bars[-2], bars[-1]
    breakout_occurred = breakout_bar.high > resistance
    return breakout_occurred and last_bar.close < resistance


# --- Downside mirrors ---------------------------------------------------------
# detect_breakout_continuation/detect_failed_breakout above are deliberately
# upside-only (see strategy/momentum_breakout.py's module docstring: "CALLS
# ONLY... a mirrored bearish detector is real, legitimate future work; this
# strategy doesn't half-implement that to look more complete"). These two
# functions are that mirror — needed by any two-sided market (e.g. a BTC
# up/down prediction market, which has a genuine bearish/NO thesis, not just
# a bullish/YES one) — built the same way, just reading support/lows instead
# of resistance/highs.

def detect_breakdown_continuation(
    bars: Sequence[PriceBar], support_lookback: int = 20, confirm_bars: int = 2
) -> bool:
    """True if price broke below the support formed by the
    `support_lookback` bars immediately preceding the most recent
    `confirm_bars`, and has closed below that support on every one of
    those confirming bars. Mirrors detect_breakout_continuation exactly,
    reading lows/support instead of highs/resistance."""
    total_needed = support_lookback + confirm_bars
    if len(bars) < total_needed:
        return False

    support_window = bars[-total_needed:-confirm_bars]
    support = min(b.low for b in support_window)
    confirming = bars[-confirm_bars:]
    return all(b.close < support for b in confirming)


def detect_failed_breakdown(bars: Sequence[PriceBar], support_lookback: int = 20) -> bool:
    """True if the second-to-last bar broke below the support formed by
    the `support_lookback` bars before it, but the most recent close has
    risen back above that support. Mirrors detect_failed_breakout."""
    total_needed = support_lookback + 2
    if len(bars) < total_needed:
        return False

    support_window = bars[-total_needed:-2]
    support = min(b.low for b in support_window)
    breakdown_bar, last_bar = bars[-2], bars[-1]
    breakdown_occurred = breakdown_bar.low < support
    return breakdown_occurred and last_bar.close > support


def detect_reversal(bars: Sequence[PriceBar], *, thesis_direction: str, swing_lookback: int = 10) -> bool:
    """A confirmed two-stage structure reversal — the standard technical
    "break of structure" pattern, and deliberately STRONGER evidence than
    either a single lower-high read (higher_highs_lower_highs, which only
    ever compares highs) or a failed breakout alone (one resistance
    retest failing). This requires BOTH:

      Bullish thesis: the most recent `swing_lookback` bars made a LOWER
      high than the `swing_lookback` bars immediately before them (the
      uptrend failed to make a new high) AND a LOWER low than that same
      prior window (price has broken below the prior swing's own
      support) — the up-structure has demonstrably broken, not merely
      paused.
      Bearish thesis: the exact mirror (a higher high AND a higher low
      versus the prior swing).

    `swing_lookback` defaults to 10 (half of detect_breakout_continuation's
    20-bar resistance_lookback default) so the two windows compared here
    total 20 bars — the same order of magnitude as this module's other
    structure checks, not an arbitrarily different scale. Needs
    2 * swing_lookback bars; returns False (never guesses, never raises)
    when there isn't enough history yet — exactly like every other
    detector in this module.
    """
    if thesis_direction.lower() not in {"bullish", "bearish"}:
        raise ValueError("thesis_direction must be 'bullish' or 'bearish'")
    total_needed = swing_lookback * 2
    if len(bars) < total_needed:
        return False

    prior_window = bars[-total_needed:-swing_lookback]
    recent_window = bars[-swing_lookback:]
    prior_high = max(b.high for b in prior_window)
    recent_high = max(b.high for b in recent_window)
    prior_low = min(b.low for b in prior_window)
    recent_low = min(b.low for b in recent_window)

    if thesis_direction.lower() == "bullish":
        return recent_high < prior_high and recent_low < prior_low
    return recent_high > prior_high and recent_low > prior_low


def bid_ask_spread_pct(bid: float, ask: float) -> float:
    """Spread as a fraction of the mid price. Returns inf for an invalid or
    crossed quote so callers can't mistake missing data for a tight market."""
    if bid <= 0 or ask <= 0 or ask < bid:
        return float("inf")
    mid = (bid + ask) / 2
    return (ask - bid) / mid


def is_liquid(volume: int | None, open_interest: int | None, min_volume: int, min_open_interest: int) -> bool:
    if volume is None or open_interest is None:
        return False
    return volume >= min_volume and open_interest >= min_open_interest
