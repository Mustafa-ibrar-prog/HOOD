"""Phase 35, Part C-D — causal, day-by-day detection of
`MomentumBreakoutStrategy`'s underlying entry signal on REAL historical
daily bars.

DATA_LIMITED, DISCLOSED UP FRONT (Part C's explicit instruction: "do NOT
silently approximate... classify DATA_LIMITED"): the live strategy
computes its indicators on 5-MINUTE bars over a 180-minute (~36-bar)
lookback (`MOMENTUM_BREAKOUT_EXISTING_V1.underlying_signals`). The free
historical dataset (Phase 26/27) provides only DAILY-resolution
underlying bars. This is a genuine temporal-granularity mismatch, not a
data gap that can be reconstructed -- an EXACT historical replication of
the live strategy's entry signal is impossible. What follows is an
EXPLICITLY LABELED, DEFENSIBLE approximation: the SAME indicator
functions (`src.market.indicators`, unchanged), the SAME period COUNTS
(RSI-14, EMA-9/21, MACD-12/26/9, structure lookback-5,
breakout-20+2-confirm) and the SAME evaluate_momentum scoring
(`src.strategy.evidence`, unchanged), reinterpreted on DAILY bars with a
36-bar trailing window (chosen to match the live default's ~36-bar
window SIZE, not its economic lookback -- 36 days and 180 minutes are
NOT the same amount of calendar time, hence this whole result carries a
DATA_LIMITED classification throughout Phase 35's report, never silently
presented as equivalent to the live signal).

Nothing here optimizes, tunes, or alters any threshold from
`MOMENTUM_BREAKOUT_EXISTING_V1` (Phase 35's explicit prohibition).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.market import indicators
from src.market.models import PriceBar
from src.strategy.evidence import MomentumEvidence, MomentumState, evaluate_momentum

DAILY_LOOKBACK_BARS = 36  # matches the live default's ~36-bar (180min/5min) WINDOW SIZE -- see module docstring


@dataclass(frozen=True)
class UnderlyingSignalEvent:
    underlying_symbol: str
    signal_date: date
    underlying_price: float  # the close on signal_date -- used only for nearest-strike matching downstream
    signals_fired: tuple[str, ...]  # evaluate_momentum's own signal names, for audit


def _price_bars_from_daily_series(series: list[tuple[date, float]]) -> list[PriceBar]:
    """Builds a minimal, honest PriceBar sequence from a real (date, close)
    series (`phase31_panel_builder.build_underlying_series`'s output --
    the only real underlying series this project has). Only `close` is a
    real observed value; `open`/`high`/`low` are set equal to `close`
    because this project's underlying series carries no separate real
    daily OHLC range for the symbols in question (Phase 31's own
    `build_underlying_series` only ever kept the `close` field) --
    documented here, never silently presented as a real intraday range.
    `volume` is unavailable in this series and is set to 0 (not fabricated
    as a plausible-looking number); this makes `volume_ratio` undefined
    (DATA_LIMITED) throughout, which is reported honestly rather than
    invented from a real range statistic."""
    from datetime import datetime, timezone

    return [
        PriceBar(
            start_time=datetime(d.year, d.month, d.day, tzinfo=timezone.utc),
            open=close, high=close, low=close, close=close, volume=0,
        )
        for d, close in series
    ]


def _evidence_from_bars_at_index(bars: list[PriceBar], i: int, *, lookback_bars: int) -> MomentumEvidence | None:
    """The actual per-date computation, operating on an ALREADY-BUILT
    `bars` list and a plain integer index -- O(lookback_bars) per call,
    never O(n). `compute_momentum_evidence_at` and
    `detect_entry_signal_dates` both funnel through this so there is
    exactly one implementation of "what evidence looked like on day i,"
    never two that could silently drift apart."""
    window = bars[max(0, i + 1 - lookback_bars): i + 1]
    if len(window) < 22:
        return None
    closes = [b.close for b in window]

    rsi_series = indicators.rsi(closes, period=14)
    _, _, hist_series = indicators.macd(closes, fast=12, slow=26, signal=9)
    ema_fast_series = indicators.ema(closes, period=9)
    ema_slow_series = indicators.ema(closes, period=21)
    higher_highs, lower_highs = indicators.higher_highs_lower_highs(window, lookback=5)
    breakout_continuation = indicators.detect_breakout_continuation(window, resistance_lookback=20, confirm_bars=2)
    failed_breakout = indicators.detect_failed_breakout(window, resistance_lookback=20)

    return MomentumEvidence(
        thesis_direction="bullish",
        rsi=rsi_series[-1] if rsi_series else None,
        rsi_prev=rsi_series[-2] if len(rsi_series) >= 2 else None,
        macd_histogram=hist_series[-1] if hist_series else None,
        macd_histogram_prev=hist_series[-2] if len(hist_series) >= 2 else None,
        ema_fast=ema_fast_series[-1] if ema_fast_series else None,
        ema_slow=ema_slow_series[-1] if ema_slow_series else None,
        higher_highs=higher_highs, lower_highs=lower_highs,
        breakout_continuation=breakout_continuation, failed_breakout=failed_breakout,
        reversal_signal=False,
        volume_ratio=None,  # DATA_LIMITED -- see _price_bars_from_daily_series docstring
    )


def compute_momentum_evidence_at(
    daily_close_series: list[tuple[date, float]], as_of: date, *, lookback_bars: int = DAILY_LOOKBACK_BARS,
) -> MomentumEvidence | None:
    """Reusable by BOTH entry-signal detection (this module) and exit-time
    re-evaluation (`phase35_option_research_strategy.py`) -- mirrors
    `position_manager/monitor.py::_build_momentum_evidence`'s live pattern
    of recomputing momentum evidence FRESH from underlying bars at
    evaluation time, using the SAME indicator functions. Returns None if
    `as_of` is not found in the series or there isn't enough causal
    history yet (never a fabricated evidence bundle). This single-date
    lookup is O(n) (a linear scan for `as_of`) -- fine for the occasional
    exit-time call this is actually used for; `detect_entry_signal_dates`
    below does its OWN single forward pass instead of calling this in a
    loop, to stay O(n) overall rather than O(n^2)."""
    for i, (d, _) in enumerate(daily_close_series):
        if d == as_of:
            bars = _price_bars_from_daily_series(daily_close_series[: i + 1])
            return _evidence_from_bars_at_index(bars, i, lookback_bars=lookback_bars)
    return None


def detect_entry_signal_dates(
    underlying_symbol: str, daily_close_series: list[tuple[date, float]], *,
    lookback_bars: int = DAILY_LOOKBACK_BARS,
) -> tuple[UnderlyingSignalEvent, ...]:
    """Walks `daily_close_series` forward day by day, causally (only ever
    using bars up to and including the current day), reusing the EXACT
    live decision (`breakout_continuation AND evaluate_momentum(...).state
    == STRENGTHENING`) with the EXACT live thresholds. Returns every real
    date the signal fired -- never a fabricated or interpolated date.

    A SINGLE forward pass (bars built once, indexed directly) -- O(n)
    overall, not O(n^2) -- since this runs once per underlying over the
    ENTIRE real series (thousands of days for AAPL/SPY/GOOG), unlike
    `compute_momentum_evidence_at`'s occasional single-date lookup above."""
    bars = _price_bars_from_daily_series(daily_close_series)
    events: list[UnderlyingSignalEvent] = []

    for i, (d, close) in enumerate(daily_close_series):
        evidence = _evidence_from_bars_at_index(bars, i, lookback_bars=lookback_bars)
        if evidence is None or not evidence.breakout_continuation:
            continue  # hard gate, exactly as the live strategy applies it -- or not enough causal history yet
        assessment = evaluate_momentum(evidence)
        if assessment.state is not MomentumState.STRENGTHENING:
            continue

        events.append(UnderlyingSignalEvent(
            underlying_symbol=underlying_symbol, signal_date=d,
            underlying_price=close, signals_fired=assessment.signals,
        ))

    return tuple(events)
