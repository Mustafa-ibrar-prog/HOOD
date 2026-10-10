"""The "one structured BTC market assessment" for the Polymarket
dynamic-exit system: STRENGTHENING / STABLE / WEAKENING / REVERSING /
INSUFFICIENT_DATA, with a numerical evidence score and the individual
signals that produced it.

This module is deliberately thin. The actual scoring — the thing that
decides whether a bundle of technical signals adds up to WEAKENING or
REVERSING, including the "a single soft signal is never enough"
guarantee — is `src/strategy/evidence.py`'s `evaluate_momentum()`,
reused here completely UNMODIFIED. This module's only job is:

  1. Turn real BTC OHLC bars (btc_market_data.py) into a
     MomentumEvidence bundle (build_btc_momentum_evidence) — the exact
     same typed shape the options side already populates from real
     equity bars (src/market/hood_provider.py) — so there is exactly
     ONE scoring engine in this codebase, not a second, simplified one
     built just for Polymarket.
  2. Separately compute Polymarket's OWN order-book microstructure
     (assess_polymarket_microstructure) — genuinely available every
     cycle with no agent mediation, unlike real BTC spot data — and
     wrap every signal, from BOTH sources, in the uniform
     models.Signal(source, timestamp, value, direction, confidence)
     shape for full auditability.
  3. Combine them into one BtcMarketAssessment.

COMBINATION RULE (deliberate, documented, NOT a blended score): the
overall `state` is the BTC-evidence MomentumAssessment's state,
UNCHANGED. Polymarket's own order-book/price-momentum signals are
captured and reported (every one of them, with source/timestamp/
value/direction/confidence) for transparency and for a human or LLM
explaining the decision, but they do NOT alter `state` in this
version. This is a deliberate v1 simplification, not an oversight:
inventing a cross-engine blending formula (how many order-book-
imbalance points equal one RSI exhaustion point?) would itself be
exactly the kind of undocumented, untested arbitrary threshold this
system is built to avoid. BTC evidence — the thing the user is
actually trading — stays authoritative; Polymarket's own odds are a
DERIVATIVE of that thesis, reported for context, not treated as an
independent vote on it.

Every field this module's output carries traces to something
real: when there is not enough real BTC OHLC history fed in yet (see
btc_market_data.py — there is no live BTC feed wired in by default),
`state` is honestly INSUFFICIENT_DATA, never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence

from src.market.indicators import (
    detect_breakdown_continuation,
    detect_breakout_continuation,
    detect_failed_breakdown,
    detect_failed_breakout,
    detect_reversal,
    ema,
    higher_highs_lower_highs,
    macd,
    rsi,
)
from src.market.models import PriceBar
from src.polymarket.btc_market_data import BtcFeedStatus, compute_feed_status
from src.polymarket.models import OrderBookSnapshot, Signal
from src.strategy.evidence import MomentumAssessment, MomentumEvidence, MomentumState, evaluate_momentum

_OUTCOME_TO_DIRECTION = {"YES": "bullish", "NO": "bearish"}

# The DEFAULT warm-up requirement (macd_slow=26 + macd_signal=9) with
# build_btc_momentum_evidence's own default periods -- exported so a
# caller that needs this number BEFORE any bars exist (bootstrap_btc_price_history,
# run_polymarket_bot.py) can request "enough for a real assessment"
# without duplicating the arithmetic. build_btc_momentum_evidence
# itself never reads this constant -- it always computes the same
# figure fresh from whatever macd_slow/macd_signal it was actually
# called with, so overriding those periods there still works correctly
# even though this constant wouldn't reflect the override.
DEFAULT_MIN_BARS_FOR_INDICATORS = 35

# The default staleness threshold, kept in sync with (and normally
# overridden by) settings.btc_max_bar_age_seconds -- see that field's
# own docstring in settings.py for the full reasoning. This module-level
# default exists only so assess_btc_market() has a sane value when
# called without threading settings through (e.g. in tests).
DEFAULT_MAX_BAR_AGE_SECONDS = 300.0


def thesis_direction_for_outcome(outcome: str) -> str:
    """YES = betting BTC is up at close (bullish); NO = betting BTC is
    down at close (bearish). This is this system's one and only
    mapping from a held position's outcome to evaluate_momentum's
    thesis_direction — see models.OpenPosition.outcome."""
    direction = _OUTCOME_TO_DIRECTION.get(outcome)
    if direction is None:
        raise ValueError(f"outcome must be one of {sorted(_OUTCOME_TO_DIRECTION)}, got {outcome!r}")
    return direction


def build_btc_momentum_evidence(
    bars: Sequence[PriceBar],
    *,
    thesis_direction: str,
    rsi_period: int = 14,
    ema_fast_period: int = 9,
    ema_slow_period: int = 21,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    structure_lookback: int = 5,
    breakout_lookback: int = 20,
    breakout_confirm_bars: int = 2,
    reversal_swing_lookback: int = 10,
    min_bars_for_indicators: int | None = None,
) -> MomentumEvidence:
    """Translates real BTC OHLC bars into a MomentumEvidence bundle.
    evaluate_momentum() (reused unmodified) does the actual scoring —
    this function only populates its typed fields honestly.

    rsi/ema_fast/ema_slow/macd_histogram are left None (not computed at
    all) until there are at least `min_bars_for_indicators` bars
    (default: macd_slow + macd_signal, e.g. 35 — the number of bars
    needed for MACD's OWN signal-line EMA to have run through one full
    period beyond pure warm-up seeding; the same reasoning any
    technical-analysis text gives for "don't trust an indicator before
    its lookback has elapsed"). ema()/rsi()/macd() all return SOMETHING
    for any non-empty input (seeded warm-up values, by design — see
    their own docstrings), so without this explicit gate a single BTC
    bar would otherwise be wrongly treated as 4 populated indicator
    fields and skip evaluate_momentum's own INSUFFICIENT_DATA check.

    volume_ratio is always None — get_crypto_quotes (the only BTC data
    source available — see btc_market_data.py) has no volume field,
    and this function never fabricates one.

    higher_highs/lower_highs/breakout_continuation/failed_breakout/
    reversal_signal each have their own internal "not enough bars yet"
    gate (see market/indicators.py) and so are computed independently
    of the rsi/macd/ema gate above.

    `thesis_direction` selects the DIRECTIONALLY CORRECT detector pair
    for breakout/breakdown: a bullish (YES) thesis uses the upside
    detect_breakout_continuation/detect_failed_breakout; a bearish (NO)
    thesis uses the downside detect_breakdown_continuation/
    detect_failed_breakdown — never the wrong-direction pair.
    """
    if thesis_direction not in ("bullish", "bearish"):
        raise ValueError(f"thesis_direction must be 'bullish' or 'bearish', got {thesis_direction!r}")

    min_bars = min_bars_for_indicators if min_bars_for_indicators is not None else macd_slow + macd_signal

    higher_highs, lower_highs = higher_highs_lower_highs(bars, lookback=structure_lookback)

    if thesis_direction == "bullish":
        breakout_continuation = detect_breakout_continuation(
            bars, resistance_lookback=breakout_lookback, confirm_bars=breakout_confirm_bars,
        )
        failed_breakout = detect_failed_breakout(bars, resistance_lookback=breakout_lookback)
    else:
        breakout_continuation = detect_breakdown_continuation(
            bars, support_lookback=breakout_lookback, confirm_bars=breakout_confirm_bars,
        )
        failed_breakout = detect_failed_breakdown(bars, support_lookback=breakout_lookback)

    reversal_signal = detect_reversal(bars, thesis_direction=thesis_direction, swing_lookback=reversal_swing_lookback)

    rsi_value = rsi_prev = macd_hist = macd_hist_prev = ema_fast_value = ema_slow_value = None
    if len(bars) >= min_bars:
        closes = [b.close for b in bars]
        rsi_values = rsi(closes, period=rsi_period)
        ema_fast_values = ema(closes, period=ema_fast_period)
        ema_slow_values = ema(closes, period=ema_slow_period)
        _, _, histogram = macd(closes, fast=macd_fast, slow=macd_slow, signal=macd_signal)
        rsi_value = rsi_values[-1]
        rsi_prev = rsi_values[-2] if len(rsi_values) >= 2 else None
        macd_hist = histogram[-1]
        macd_hist_prev = histogram[-2] if len(histogram) >= 2 else None
        ema_fast_value = ema_fast_values[-1]
        ema_slow_value = ema_slow_values[-1]

    return MomentumEvidence(
        thesis_direction=thesis_direction,
        rsi=rsi_value, rsi_prev=rsi_prev,
        macd_histogram=macd_hist, macd_histogram_prev=macd_hist_prev,
        ema_fast=ema_fast_value, ema_slow=ema_slow_value,
        higher_highs=higher_highs, lower_highs=lower_highs,
        breakout_continuation=breakout_continuation, failed_breakout=failed_breakout,
        reversal_signal=reversal_signal,
        volume_ratio=None,
    )


def wrap_btc_signals(evidence: MomentumEvidence, *, at: datetime) -> tuple[Signal, ...]:
    """Wraps MomentumEvidence's own raw INPUT fields (not
    evaluate_momentum's derived fired-signal names) as uniform Signal
    objects — these are the real observed values, each with a real
    direction derived from its own, obvious semantics (RSI above/below
    50, EMA fast vs. slow, etc.), so nothing here needs to re-guess
    evaluate_momentum's internal scoring.

    confidence values are fixed per signal TYPE, deliberately ordered
    to roughly mirror evidence.py's own relative signal weights scaled
    to 0.0-1.0 (reversal's 0.9 vs. structure's 0.5, matching reversal's
    +3 vs. structure's +1 weight there) — an ORDINAL correspondence to
    an already-shipped, already-justified weighting, not an
    independently invented calibration.

    Public (not module-private) because btc_entry_signal.py's entry-
    direction assessment reuses this EXACT wrapping for both the
    bullish- and bearish-framed evidence it builds — never a second,
    parallel way to turn MomentumEvidence into Signals.
    """
    bullish = evidence.thesis_direction == "bullish"
    opposite = "bearish" if bullish else "bullish"
    thesis_dir = evidence.thesis_direction

    signals: list[Signal] = []

    if evidence.rsi is not None:
        direction = "bullish" if evidence.rsi > 50 else ("bearish" if evidence.rsi < 50 else "neutral")
        signals.append(Signal(source="btc_rsi", timestamp=at, value=evidence.rsi, direction=direction, confidence=0.6))

    if evidence.macd_histogram is not None:
        direction = "bullish" if evidence.macd_histogram > 0 else ("bearish" if evidence.macd_histogram < 0 else "neutral")
        signals.append(Signal(
            source="btc_macd_histogram", timestamp=at, value=evidence.macd_histogram, direction=direction, confidence=0.6,
        ))

    if evidence.ema_fast is not None and evidence.ema_slow is not None:
        spread = evidence.ema_fast - evidence.ema_slow
        direction = "bullish" if spread > 0 else ("bearish" if spread < 0 else "neutral")
        signals.append(Signal(source="btc_ema_trend", timestamp=at, value=spread, direction=direction, confidence=0.6))

    if evidence.higher_highs or evidence.lower_highs:
        direction = "bullish" if evidence.higher_highs else "bearish"
        signals.append(Signal(
            source="btc_structure", timestamp=at, value=evidence.higher_highs, direction=direction, confidence=0.5,
        ))

    if evidence.breakout_continuation:
        signals.append(Signal(
            source="btc_breakout_continuation", timestamp=at, value=True, direction=thesis_dir, confidence=0.7,
        ))
    if evidence.failed_breakout:
        signals.append(Signal(
            source="btc_failed_breakout", timestamp=at, value=True, direction=opposite, confidence=0.7,
        ))
    if evidence.reversal_signal:
        signals.append(Signal(
            source="btc_reversal", timestamp=at, value=True, direction=opposite, confidence=0.9,
        ))

    return tuple(signals)


def assess_polymarket_microstructure(
    order_book: OrderBookSnapshot, recent_mids: Sequence[float], *, outcome: str, now: datetime | None = None,
) -> tuple[Signal, ...]:
    """Polymarket's own order-book microstructure — genuinely available
    every cycle without any agent mediation (get_order_book() is a
    direct, unattended HTTP call), unlike real BTC spot data. See this
    module's docstring on why these signals are reported but do not
    alter assess_btc_market()'s overall `state` in this version.

    `direction` throughout is expressed in ABSOLUTE BTC terms (bullish
    = evidence BTC is more likely up), not "favorable for this
    position" — translated from "buy pressure on THIS outcome token"
    via `outcome`: more buying interest in the YES token is a bullish
    BTC signal; more buying interest in the NO token is a bearish one.
    """
    if outcome not in ("YES", "NO"):
        raise ValueError(f"outcome must be 'YES' or 'NO', got {outcome!r}")
    now = now or datetime.now(timezone.utc)
    buy_pressure_direction = "bullish" if outcome == "YES" else "bearish"
    sell_pressure_direction = "bearish" if outcome == "YES" else "bullish"

    signals: list[Signal] = []

    bid_depth = sum(level.size for level in order_book.bids)
    ask_depth = sum(level.size for level in order_book.asks)
    if bid_depth + ask_depth > 0:
        imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
        if imbalance > 0.1:
            direction = buy_pressure_direction
        elif imbalance < -0.1:
            direction = sell_pressure_direction
        else:
            direction = "neutral"
        signals.append(Signal(
            source="polymarket_order_book_imbalance", timestamp=now, value=round(imbalance, 4),
            direction=direction, confidence=min(0.6, 0.3 + abs(imbalance)),
        ))

    if order_book.spread_pct is not None:
        signals.append(Signal(
            source="polymarket_bid_ask_spread", timestamp=now, value=order_book.spread_pct,
            direction="neutral", confidence=0.3,
        ))

    samples = [m for m in recent_mids if m is not None]
    if len(samples) >= 2:
        move = samples[-1] - samples[0]
        if abs(move) > 1e-9:
            direction = buy_pressure_direction if move > 0 else sell_pressure_direction
            signals.append(Signal(
                source="polymarket_price_momentum", timestamp=now, value=round(move, 4),
                direction=direction, confidence=min(0.5, 0.2 + abs(move)),
            ))

    # A coarse, well-known trade-classification heuristic (compare the
    # last executed price to the current mid — a trade printing above
    # mid likely lifted the ask/was buyer-initiated, below mid likely
    # hit the bid/was seller-initiated). Real data from Polymarket US's
    # own MarketBook.stats (us_client.get_order_book) — never a true
    # aggressor-flagged trade tape, which this SDK does not expose; see
    # OrderBookSnapshot.last_trade_price's docstring.
    if order_book.last_trade_price is not None and order_book.mid is not None:
        if order_book.last_trade_price > order_book.mid:
            direction = buy_pressure_direction
        elif order_book.last_trade_price < order_book.mid:
            direction = sell_pressure_direction
        else:
            direction = "neutral"
        signals.append(Signal(
            source="polymarket_trade_flow", timestamp=now, value=order_book.last_trade_price,
            direction=direction, confidence=0.3,
        ))

    return tuple(signals)


@dataclass(frozen=True)
class BtcMarketAssessment:
    """The "one structured BTC market assessment" — state plus a
    numerical evidence score plus every individual signal that
    produced it, BTC and Polymarket microstructure alike, uniformly
    represented. See module docstring for the combination rule.

    `feed_status` is the answer to "was the BTC data behind `state`
    actually fresh" — see btc_market_data.compute_feed_status. A
    STALE or UNAVAILABLE status means `state` is guaranteed to be
    INSUFFICIENT_DATA (the bars were never even handed to
    build_btc_momentum_evidence — see assess_btc_market below); this
    field exists so exit_manager.py can log exactly WHY (dead feed vs.
    genuinely insufficient history) rather than just the end result."""

    state: MomentumState
    evidence_score: int  # weakening_score - strengthening_score from the BTC evaluate_momentum() call; positive = net weakening/reversing
    btc_assessment: MomentumAssessment  # the raw evaluate_momentum() output (weakening_score/strengthening_score/fired signal names)
    signals: tuple[Signal, ...]  # every Signal, BTC + Polymarket microstructure
    # Defaults to a synthetic "FRESH, unknown source" status so tests
    # that construct a BtcMarketAssessment directly (to isolate the
    # evaluate_dynamic_exit cascade from this module's own bar-aggregation/
    # staleness logic -- see tests/test_polymarket_exit_manager.py's
    # _assessment() helper) don't need to care about it. assess_btc_market()
    # ALWAYS passes a real, computed one explicitly.
    feed_status: BtcFeedStatus = field(default_factory=lambda: BtcFeedStatus(
        source=None, last_bar_time=None, bar_age_seconds=None, status="FRESH",
    ))

    @property
    def signal_count(self) -> int:
        return len(self.btc_assessment.signals)


def assess_btc_market(
    bars: Sequence[PriceBar],
    order_book: OrderBookSnapshot,
    recent_mids: Sequence[float],
    *,
    outcome: str,
    now: datetime | None = None,
    max_bar_age_seconds: float = DEFAULT_MAX_BAR_AGE_SECONDS,
    feed_source: str = "manual",
    **evidence_kwargs,
) -> BtcMarketAssessment:
    """The single entry point check_and_execute_dynamic_exits() (see
    exit_manager.py) calls once per open position per cycle.

    STALE-FEED SAFETY: before anything else, this checks whether the
    NEWEST available bar (if any) is within `max_bar_age_seconds` of
    `now` (see btc_market_data.compute_feed_status). If it is not —
    the feed is STALE (bars exist but stopped updating) or UNAVAILABLE
    (no bars at all) — `bars` is NEVER handed to
    build_btc_momentum_evidence(); an empty sequence is used instead,
    guaranteeing `state == INSUFFICIENT_DATA` exactly as if nothing had
    ever been fed. This is what makes a feed that goes silent AFTER
    building real history behave identically to a feed that was never
    wired up at all, rather than freezing on whatever evidence it last
    saw (see btc_market_data.py's and settings.py's module docstrings
    for why this matters).

    `now` is also used for timestamping the Polymarket microstructure
    signals and the BTC-signal wrapper (use the latest USABLE bar's
    own start_time when one exists, so the assessment doesn't silently
    claim to be "as of now" when its real BTC evidence is actually
    older)."""
    now = now or datetime.now(timezone.utc)
    feed_status = compute_feed_status(list(bars), max_bar_age_seconds=max_bar_age_seconds, source=feed_source, now=now)
    usable_bars = bars if feed_status.status == "FRESH" else []

    thesis_direction = thesis_direction_for_outcome(outcome)
    evidence = build_btc_momentum_evidence(usable_bars, thesis_direction=thesis_direction, **evidence_kwargs)
    assessment = evaluate_momentum(evidence)

    signal_time = usable_bars[-1].start_time if usable_bars else now
    btc_signals = wrap_btc_signals(evidence, at=signal_time)
    microstructure_signals = assess_polymarket_microstructure(order_book, recent_mids, outcome=outcome, now=now)

    return BtcMarketAssessment(
        state=assessment.state,
        evidence_score=assessment.weakening_score - assessment.strengthening_score,
        btc_assessment=assessment,
        signals=btc_signals + microstructure_signals,
        feed_status=feed_status,
    )
