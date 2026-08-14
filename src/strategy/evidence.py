"""Momentum-evidence scoring.

This is the "measurable evidence" engine behind the position manager's
early-exit logic: it looks at a bundle of technical signals and decides
whether a move is STRENGTHENING, STABLE, WEAKENING, or REVERSING relative
to the trade's original (bullish/bearish) direction.

Design intent, straight from the requirements:
  - A single soft signal (e.g. RSI ticking down one bar, volume dipping a
    little) must NOT be enough to call a move "weakening." Price pausing
    is not evidence of anything by itself.
  - Multiple corroborating signals (structure break + momentum rollover +
    volume drying up + trend flip, etc.) are what earns a WEAKENING or
    REVERSING classification.
  - Missing/None inputs never get inferred into a verdict — they push the
    result toward INSUFFICIENT_DATA, which callers must treat as "hold,
    don't act on this."
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MomentumState(str, Enum):
    STRENGTHENING = "STRENGTHENING"
    STABLE = "STABLE"
    WEAKENING = "WEAKENING"
    REVERSING = "REVERSING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# Minimum number of weighted "weakening points" required before the engine
# will call a move WEAKENING, and the higher bar for REVERSING. Tuned so a
# lone signal never crosses the line — see module docstring.
WEAKENING_THRESHOLD = 3
REVERSING_THRESHOLD = 5

# Minimum number of the *required* raw fields that must be present before
# the engine will produce anything other than INSUFFICIENT_DATA.
_REQUIRED_FIELDS = ("rsi", "macd_histogram", "ema_fast", "ema_slow", "volume_ratio")


@dataclass(frozen=True)
class MomentumEvidence:
    """Raw signal inputs for one evaluation cycle. All indicator fields are
    optional (None = "not available this cycle") — the scorer degrades to
    INSUFFICIENT_DATA rather than guessing.

    thesis_direction orients every signal: e.g. for a bearish (long put)
    thesis, "lower highs" is the favorable structure and "higher highs" is
    the unfavorable one. Callers pass raw up/down facts; this module does
    the direction-relative interpretation.
    """

    thesis_direction: str  # "bullish" or "bearish"

    rsi: float | None = None
    rsi_prev: float | None = None

    macd_histogram: float | None = None
    macd_histogram_prev: float | None = None

    ema_fast: float | None = None
    ema_slow: float | None = None

    higher_highs: bool = False
    lower_highs: bool = False

    breakout_continuation: bool = False
    failed_breakout: bool = False
    reversal_signal: bool = False

    volume_ratio: float | None = None  # recent volume / average volume

    def __post_init__(self) -> None:
        if self.thesis_direction.lower() not in {"bullish", "bearish"}:
            raise ValueError("thesis_direction must be 'bullish' or 'bearish'")

    @property
    def is_bullish(self) -> bool:
        return self.thesis_direction.lower() == "bullish"

    def available_field_count(self) -> int:
        return sum(1 for name in _REQUIRED_FIELDS if getattr(self, name) is not None)


@dataclass(frozen=True)
class MomentumAssessment:
    state: MomentumState
    weakening_score: int
    strengthening_score: int
    signals: tuple[str, ...]  # human-readable signal names that fired


def evaluate_momentum(evidence: MomentumEvidence) -> MomentumAssessment:
    """Score a MomentumEvidence bundle into a MomentumState.

    Never raises on missing data — missing data degrades the result to
    INSUFFICIENT_DATA, which is itself a safe, actionable state (callers
    should HOLD, not guess).
    """

    if evidence.available_field_count() < 3:
        return MomentumAssessment(MomentumState.INSUFFICIENT_DATA, 0, 0, ())

    bullish = evidence.is_bullish
    signals: list[str] = []
    weakening = 0
    strengthening = 0

    # --- Trend (EMA fast vs. slow) -----------------------------------------
    trend_favorable: bool | None = None
    if evidence.ema_fast is not None and evidence.ema_slow is not None:
        trend_favorable = (
            evidence.ema_fast > evidence.ema_slow
            if bullish
            else evidence.ema_fast < evidence.ema_slow
        )
        if trend_favorable:
            strengthening += 1
            signals.append("trend_intact")
        else:
            weakening += 2
            signals.append("trend_flip")

    # --- Structure (higher highs / lower highs) -----------------------------
    structure_favorable = (
        evidence.higher_highs and not evidence.lower_highs
        if bullish
        else evidence.lower_highs and not evidence.higher_highs
    )
    structure_unfavorable = (
        evidence.lower_highs and not evidence.higher_highs
        if bullish
        else evidence.higher_highs and not evidence.lower_highs
    )
    if structure_favorable:
        strengthening += 1
        signals.append("structure_confirming")
    if structure_unfavorable:
        weakening += 1
        signals.append("structure_turning")

    # --- Breakout behavior ---------------------------------------------------
    if evidence.breakout_continuation:
        strengthening += 2
        signals.append("breakout_continuation")
    if evidence.failed_breakout:
        weakening += 2
        signals.append("failed_breakout")
    if evidence.reversal_signal:
        weakening += 3
        signals.append("reversal_signal")

    # --- RSI exhaustion / rollover -------------------------------------------
    exhaustion = False
    rolling_over = False
    if evidence.rsi is not None:
        exhaustion = evidence.rsi >= 70 if bullish else evidence.rsi <= 30
        if exhaustion and evidence.rsi_prev is not None:
            rolling_over = evidence.rsi < evidence.rsi_prev if bullish else evidence.rsi > evidence.rsi_prev
    if exhaustion and rolling_over:
        weakening += 2
        signals.append("momentum_exhaustion")
    elif exhaustion:
        weakening += 1
        signals.append("overbought_overextended" if bullish else "oversold_overextended")
    elif evidence.rsi is not None and (50 <= evidence.rsi <= 70 if bullish else 30 <= evidence.rsi <= 50):
        strengthening += 1
        signals.append("rsi_healthy_range")

    # --- MACD histogram fading -------------------------------------------------
    if evidence.macd_histogram is not None and evidence.macd_histogram_prev is not None:
        fading = (
            evidence.macd_histogram < evidence.macd_histogram_prev
            if bullish
            else evidence.macd_histogram > evidence.macd_histogram_prev
        )
        favorable_side = (
            evidence.macd_histogram > 0 if bullish else evidence.macd_histogram < 0
        )
        if fading and (exhaustion or structure_unfavorable or not favorable_side):
            weakening += 1
            signals.append("macd_momentum_fading")
        elif favorable_side and not fading:
            strengthening += 1
            signals.append("macd_momentum_confirming")

    # --- Volume ---------------------------------------------------------------
    if evidence.volume_ratio is not None:
        if evidence.volume_ratio < 0.7 and not evidence.breakout_continuation:
            weakening += 1
            signals.append("volume_drying_up")
        elif evidence.volume_ratio > 1.2:
            strengthening += 1
            signals.append("volume_confirming")

    if weakening >= REVERSING_THRESHOLD:
        state = MomentumState.REVERSING
    elif weakening >= WEAKENING_THRESHOLD:
        state = MomentumState.WEAKENING
    elif strengthening > weakening:
        state = MomentumState.STRENGTHENING
    else:
        state = MomentumState.STABLE

    return MomentumAssessment(state, weakening, strengthening, tuple(signals))
