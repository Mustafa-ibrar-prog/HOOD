"""Tests for the BTC/Polymarket structured market assessment
(btc_intelligence.py). evaluate_momentum() itself (src/strategy/
evidence.py) is reused unmodified and already has its own test suite
(tests/test_evidence.py) -- these tests focus on this module's own
job: translating real bars into MomentumEvidence correctly (including
the min-bars gate and direction-aware detector selection), wrapping
signals faithfully, and the documented BTC-authoritative combination
rule.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.market.models import PriceBar
from src.polymarket.btc_intelligence import (
    assess_btc_market,
    assess_polymarket_microstructure,
    build_btc_momentum_evidence,
    thesis_direction_for_outcome,
)
from src.polymarket.models import BookLevel, OrderBookSnapshot
from src.strategy.evidence import MomentumState

_BASE = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def _bars(closes: list[float], *, start: datetime = _BASE) -> list[PriceBar]:
    bars = []
    for i, close in enumerate(closes):
        bars.append(PriceBar(
            start_time=start + timedelta(minutes=i), open=close, high=close + 0.5, low=close - 0.5,
            close=close, volume=0,
        ))
    return bars


def _book(**overrides) -> OrderBookSnapshot:
    defaults = dict(
        token_id="t", bids=(BookLevel(price=0.48, size=100.0),), asks=(BookLevel(price=0.52, size=100.0),),
        fetched_at=_BASE,
    )
    defaults.update(overrides)
    return OrderBookSnapshot(**defaults)


# --- thesis_direction_for_outcome ---------------------------------------------

def test_thesis_direction_maps_yes_bullish_no_bearish():
    assert thesis_direction_for_outcome("YES") == "bullish"
    assert thesis_direction_for_outcome("NO") == "bearish"


def test_thesis_direction_rejects_invalid_outcome():
    with pytest.raises(ValueError):
        thesis_direction_for_outcome("MAYBE")


# --- build_btc_momentum_evidence: the min-bars gate ---------------------------

def test_too_few_bars_leaves_rsi_macd_ema_none():
    """Below min_bars_for_indicators (default macd_slow+macd_signal=35),
    rsi/macd/ema must stay None -- NOT a technically-computed-but-
    meaningless warm-up value -- so evaluate_momentum() correctly sees
    < 3 required fields and returns INSUFFICIENT_DATA."""
    bars = _bars([100.0 + i * 0.1 for i in range(34)])
    evidence = build_btc_momentum_evidence(bars, thesis_direction="bullish")
    assert evidence.rsi is None
    assert evidence.macd_histogram is None
    assert evidence.ema_fast is None
    assert evidence.ema_slow is None
    assert evidence.available_field_count() == 0


def test_enough_bars_populates_rsi_macd_ema():
    bars = _bars([100.0 + i * 0.1 for i in range(35)])
    evidence = build_btc_momentum_evidence(bars, thesis_direction="bullish")
    assert evidence.rsi is not None
    assert evidence.macd_histogram is not None
    assert evidence.ema_fast is not None
    assert evidence.ema_slow is not None


def test_min_bars_override_is_honored():
    bars = _bars([100.0 + i * 0.1 for i in range(10)])
    evidence = build_btc_momentum_evidence(bars, thesis_direction="bullish", min_bars_for_indicators=5)
    assert evidence.rsi is not None


def test_rejects_invalid_thesis_direction():
    bars = _bars([100.0] * 40)
    with pytest.raises(ValueError):
        build_btc_momentum_evidence(bars, thesis_direction="sideways")


# --- Direction-aware detector selection ---------------------------------------

def test_bullish_thesis_uses_upside_breakout_detector():
    pre = [100.0 + (i % 3) * 0.1 for i in range(20)]
    confirm = [103.0, 104.0]
    bars = _bars(pre + confirm)
    evidence = build_btc_momentum_evidence(bars, thesis_direction="bullish", breakout_lookback=20, breakout_confirm_bars=2)
    assert evidence.breakout_continuation is True


def test_bearish_thesis_uses_downside_breakdown_detector():
    pre = [100.0 + (i % 3) * 0.1 for i in range(20)]
    confirm = [97.0, 96.0]
    bars = _bars(pre + confirm)
    evidence = build_btc_momentum_evidence(bars, thesis_direction="bearish", breakout_lookback=20, breakout_confirm_bars=2)
    assert evidence.breakout_continuation is True


def test_bullish_thesis_never_sees_a_downside_move_as_continuation():
    """A clean downside breakdown must NOT register as
    breakout_continuation for a bullish thesis (wrong-direction
    detector would be a real bug, not just a missed signal)."""
    pre = [100.0 + (i % 3) * 0.1 for i in range(20)]
    confirm = [97.0, 96.0]
    bars = _bars(pre + confirm)
    evidence = build_btc_momentum_evidence(bars, thesis_direction="bullish", breakout_lookback=20, breakout_confirm_bars=2)
    assert evidence.breakout_continuation is False


# --- volume_ratio is always honestly None -------------------------------------

def test_volume_ratio_is_always_none():
    bars = _bars([100.0 + i * 0.1 for i in range(40)])
    evidence = build_btc_momentum_evidence(bars, thesis_direction="bullish")
    assert evidence.volume_ratio is None


# --- assess_polymarket_microstructure -----------------------------------------

def test_microstructure_imbalance_favors_yes_buy_pressure():
    book = _book(bids=(BookLevel(price=0.48, size=200.0),), asks=(BookLevel(price=0.52, size=50.0),))
    signals = assess_polymarket_microstructure(book, [], outcome="YES", now=_BASE)
    imbalance_signal = next(s for s in signals if s.source == "polymarket_order_book_imbalance")
    assert imbalance_signal.direction == "bullish"  # more bid depth on the YES token -> bullish BTC


def test_microstructure_imbalance_on_no_token_flips_to_bearish():
    """The SAME raw buy-pressure (more bid depth) on the NO token means
    more confidence BTC goes DOWN -- bearish, not bullish."""
    book = _book(bids=(BookLevel(price=0.48, size=200.0),), asks=(BookLevel(price=0.52, size=50.0),))
    signals = assess_polymarket_microstructure(book, [], outcome="NO", now=_BASE)
    imbalance_signal = next(s for s in signals if s.source == "polymarket_order_book_imbalance")
    assert imbalance_signal.direction == "bearish"


def test_microstructure_price_momentum_from_recent_mids():
    book = _book()
    signals = assess_polymarket_microstructure(book, [0.40, 0.45, 0.50], outcome="YES", now=_BASE)
    momentum_signal = next(s for s in signals if s.source == "polymarket_price_momentum")
    assert momentum_signal.direction == "bullish"
    assert momentum_signal.value == pytest.approx(0.10)


def test_microstructure_trade_flow_above_mid_is_buy_pressure():
    book = _book(bids=(BookLevel(price=0.48, size=10),), asks=(BookLevel(price=0.52, size=10),), last_trade_price=0.51)
    signals = assess_polymarket_microstructure(book, [], outcome="YES", now=_BASE)
    trade_flow = next(s for s in signals if s.source == "polymarket_trade_flow")
    assert trade_flow.direction == "bullish"  # printed above mid (0.50) -- likely lifted the ask


def test_microstructure_rejects_invalid_outcome():
    with pytest.raises(ValueError):
        assess_polymarket_microstructure(_book(), [], outcome="MAYBE")


def test_microstructure_empty_book_and_no_mids_produces_no_crash():
    book = OrderBookSnapshot(token_id="t", bids=(), asks=(), fetched_at=_BASE)
    signals = assess_polymarket_microstructure(book, [], outcome="YES", now=_BASE)
    assert signals == ()  # nothing available -- never fabricated


# --- assess_btc_market: the combined assessment -------------------------------

def test_insufficient_btc_data_yields_insufficient_state_regardless_of_microstructure():
    """Requirement: insufficient data -> HOLD, never guess. Even with
    a strongly bullish Polymarket order book, no real BTC history
    means the overall state must stay INSUFFICIENT_DATA."""
    bars = _bars([100.0] * 5)  # far below the 35-bar minimum
    book = _book(bids=(BookLevel(price=0.48, size=1000.0),), asks=(BookLevel(price=0.52, size=1.0),))
    assessment = assess_btc_market(bars, book, [0.3, 0.4, 0.5], outcome="YES", now=_BASE)
    assert assessment.state == MomentumState.INSUFFICIENT_DATA


def test_sufficient_strengthening_btc_data_yields_strengthening_state():
    # A mild, healthy uptrend with real pullbacks (not a straight line
    # pinned at RSI 100, which reads as overbought/exhausted -- see
    # evaluate_momentum's own RSI-exhaustion handling): trend intact,
    # RSI in its healthy 50-70 range, MACD on the favorable side.
    import math
    closes = [100.0 + i * 0.05 + 1.0 * math.sin(i / 2.0) for i in range(45)]
    bars = _bars(closes)
    book = _book()
    assessment = assess_btc_market(bars, book, [0.4, 0.45], outcome="YES", now=_BASE)
    assert assessment.state == MomentumState.STRENGTHENING
    assert assessment.evidence_score < 0  # net strengthening (negative weakening-minus-strengthening)


def test_assessment_signals_include_both_btc_and_microstructure_sources():
    bars = _bars([100.0 + i * 0.3 for i in range(40)])
    book = _book()
    assessment = assess_btc_market(bars, book, [0.4, 0.45], outcome="YES", now=_BASE)
    sources = {s.source for s in assessment.signals}
    assert any(s.startswith("btc_") for s in sources)
    assert any(s.startswith("polymarket_") for s in sources)


def test_assessment_embeds_the_raw_btc_assessment_for_full_detail():
    bars = _bars([100.0 + i * 0.3 for i in range(40)])
    book = _book()
    assessment = assess_btc_market(bars, book, [], outcome="YES", now=_BASE)
    assert assessment.btc_assessment.state == assessment.state
    assert assessment.signal_count == len(assessment.btc_assessment.signals)


# --- Stale-feed safety: assess_btc_market()'s max_bar_age_seconds gate -------

def test_fresh_bars_within_threshold_use_real_evidence():
    bars = _bars([100.0 + i * 0.3 for i in range(40)])
    now = bars[-1].start_time + timedelta(seconds=30)  # well within a 300s threshold
    book = _book()
    assessment = assess_btc_market(bars, book, [], outcome="YES", now=now, max_bar_age_seconds=300)
    assert assessment.feed_status.status == "FRESH"
    assert assessment.state != MomentumState.INSUFFICIENT_DATA


def test_stale_bars_force_insufficient_data_despite_plenty_of_history():
    """A feed that built real history and then went silent must behave
    IDENTICALLY to a feed that was never fed at all -- never keep
    deciding from old data forever."""
    bars = _bars([100.0 + i * 0.3 for i in range(40)])  # 40 bars -- otherwise easily enough for a real read
    now = bars[-1].start_time + timedelta(seconds=301)  # just past a 300s threshold
    book = _book()
    assessment = assess_btc_market(bars, book, [], outcome="YES", now=now, max_bar_age_seconds=300)
    assert assessment.feed_status.status == "STALE"
    assert assessment.state == MomentumState.INSUFFICIENT_DATA


def test_no_bars_at_all_is_unavailable_not_stale():
    now = _BASE
    assessment = assess_btc_market([], _book(), [], outcome="YES", now=now, max_bar_age_seconds=300)
    assert assessment.feed_status.status == "UNAVAILABLE"
    assert assessment.state == MomentumState.INSUFFICIENT_DATA


def test_feed_status_source_label_is_threaded_through():
    bars = _bars([100.0 + i * 0.3 for i in range(40)])
    now = bars[-1].start_time + timedelta(seconds=30)
    assessment = assess_btc_market(bars, _book(), [], outcome="YES", now=now, feed_source="coinbase")
    assert assessment.feed_status.source == "coinbase"


def test_same_stale_rule_applies_after_a_simulated_restart():
    """Restart-safety at the assessment level: the SAME bars, read by
    a fresh call (standing in for a brand-new process after a
    restart), are judged purely by real elapsed time vs. the bar's own
    timestamp -- never by anything cached in memory. A restart does
    not "refresh" staleness; only new, real data does."""
    bars = _bars([100.0 + i * 0.3 for i in range(40)])
    fresh_now = bars[-1].start_time + timedelta(seconds=10)
    stale_now = bars[-1].start_time + timedelta(hours=2)  # the "restart" happens long after the feed died
    book = _book()

    fresh_assessment = assess_btc_market(bars, book, [], outcome="YES", now=fresh_now, max_bar_age_seconds=300)
    restarted_assessment = assess_btc_market(bars, book, [], outcome="YES", now=stale_now, max_bar_age_seconds=300)

    assert fresh_assessment.feed_status.status == "FRESH"
    assert restarted_assessment.feed_status.status == "STALE"
    assert restarted_assessment.state == MomentumState.INSUFFICIENT_DATA
