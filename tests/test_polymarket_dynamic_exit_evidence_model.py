"""Replay tests for the v2 continuous evidence/expected-value dynamic-exit
model -- the exact 8 scenarios the redesign was specified against:

  1. -50% P&L + strongly improving BTC evidence -> HOLD
  2. -50% P&L + strongly deteriorating BTC evidence -> EXIT
  3. +10% P&L + deteriorating evidence -> EXIT
  4. +20% P&L + improving evidence -> HOLD
  5. small loss + improving evidence -> HOLD
  6. conflicting BTC signals -> HOLD
  7. stale feed -> HOLD
  8. strong positive edge regardless of P&L -> HOLD

Unlike test_polymarket_exit_manager.py's cascade-level unit tests (which
construct a BtcMarketAssessment directly), every scenario here is driven
by REAL OHLC BTC bars (plus real recent Polymarket mid-price history)
through the production pipeline this redesign actually ships
(assess_btc_market -> build_btc_momentum_evidence -> evaluate_momentum ->
Signal-wrapping -> evaluate_dynamic_exit's compute_edge_assessment), so
what's being proven is the real, end-to-end behavior, not just the
cascade's branching in isolation.

Every scenario uses outcome="YES" (a bullish thesis), consistent with the
rest of this test suite -- "improving" means bullish-for-BTC evidence,
"deteriorating" means bearish-for-BTC evidence.

Scenario 6 (conflicting) reuses the exact pinned (drift, noise, seed)
random-walk fixture tests/test_polymarket_dynamic_exit_replay.py already
verified produces STABLE evidence (weakening_score below
WEAKENING_THRESHOLD) -- genuinely ambiguous evidence under
evaluate_momentum's own calibrated scoring, not a hand-engineered tie.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

import pytest

from src.market.models import PriceBar
from src.polymarket.btc_intelligence import assess_btc_market
from src.polymarket.exit_manager import evaluate_dynamic_exit
from src.polymarket.models import BookLevel, OrderBookSnapshot
from src.polymarket.positions import OpenPosition
from src.strategy.evidence import MomentumState

_BASE = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def _bars(closes: list[float], *, start: datetime = _BASE) -> list[PriceBar]:
    return [
        PriceBar(start_time=start + timedelta(minutes=i), open=c, high=c + 0.5, low=c - 0.5, close=c, volume=0)
        for i, c in enumerate(closes)
    ]


def _book(bid: float, ask: float | None = None, *, size: float = 100.0) -> OrderBookSnapshot:
    ask = ask if ask is not None else round(bid + 0.02, 4)
    return OrderBookSnapshot(
        token_id="tok-replay", bids=(BookLevel(price=bid, size=size),), asks=(BookLevel(price=ask, size=size),),
        fetched_at=_BASE,
    )


def _position(avg_fill_price: float, *, close_time: datetime = _BASE + timedelta(minutes=10)) -> OpenPosition:
    return OpenPosition(
        condition_id="cpc-btc-updown-15m-replay", token_id="tok-replay", outcome="YES",
        requested_size_usd=5.0, filled_shares=5.0, avg_fill_price=avg_fill_price, order_id="replay-order",
        client_order_id="replay-client", status="filled", opened_at=_BASE, close_time=close_time,
    )


def _assess(closes, book, recent_mids, *, now=None, max_bar_age_seconds: float = 300.0):
    return assess_btc_market(
        _bars(closes), book, recent_mids, outcome="YES", now=now or _BASE, max_bar_age_seconds=max_bar_age_seconds,
    )


# --- Realistic BTC bar sequences, built once and reused across scenarios ----
# that only vary the position's entry price / current bid (i.e. P&L) against
# the SAME underlying evidence -- directly demonstrating that varying P&L
# alone, with evidence held fixed, never flips the decision.

# A mild, healthy uptrend with real pullbacks (not a straight line pinned at
# RSI 100) -- the exact pattern already proven to read as STRENGTHENING in
# tests/test_polymarket_btc_intelligence.py. Paired with ascending recent
# Polymarket mids (buy pressure confirming the same bullish thesis).
_IMPROVING_CLOSES = [100.0 + i * 0.05 + 1.0 * math.sin(i / 2.0) for i in range(45)]
_IMPROVING_RECENT_MIDS = [0.40, 0.45]

# A clean uptrend (building the "prior swing" detect_reversal compares
# against) followed by a sharp, sustained decline: breaks structure (lower
# highs), triggers detect_reversal (lower high AND lower low than the prior
# swing), flips the EMA trend and MACD histogram bearish, and rolls RSI over
# -- REVERSING by a wide margin. Paired with descending recent Polymarket
# mids (sell pressure confirming the same bearish-for-the-thesis evidence),
# so every single fired signal -- BTC and Polymarket alike -- opposes a YES
# thesis (see test_deteriorating_bars_produce_only_opposing_signals).
_UP_LEG = [100.0 + i * 0.5 for i in range(25)]
_DETERIORATING_CLOSES = _UP_LEG + [_UP_LEG[-1] - i * 0.8 for i in range(1, 26)]
_DETERIORATING_RECENT_MIDS = [0.45, 0.40]


def _drifting_noisy_closes(*, drift: float, noise: float, seed: int, n: int = 45) -> list[float]:
    """A seeded random walk: closes[i] = closes[i-1] + drift + U(-noise,
    noise) -- same generator as
    tests/test_polymarket_dynamic_exit_replay.py's own helper, reused
    verbatim (deterministic: same seed always produces the exact same
    closes)."""
    r = random.Random(seed)
    closes = [100.0]
    for _ in range(1, n):
        closes.append(closes[-1] + drift + r.uniform(-noise, noise))
    return closes


# The exact (drift, noise, seed) tests/test_polymarket_dynamic_exit_replay.py
# already pinned as producing STABLE evidence (weakening_score=2, below
# evaluate_momentum's own WEAKENING_THRESHOLD=3) -- genuinely ambiguous
# real evidence, not an engineered tie.
_CONFLICTING_CLOSES = _drifting_noisy_closes(drift=-0.013308557506160237, noise=0.1303950481189401, seed=795667)


# --- Sanity pins on the fixture bar sequences themselves ---------------------
# (so a future change to the indicator math that silently stops producing
# "strongly improving"/"strongly deteriorating"/"conflicting" evidence fails
# loudly here, not by a mysteriously-wrong HOLD/EXIT below.)

def test_improving_bars_produce_only_supporting_signals():
    assessment = _assess(_IMPROVING_CLOSES, _book(bid=0.48), _IMPROVING_RECENT_MIDS)
    assert assessment.state is MomentumState.STRENGTHENING
    opposing = [s for s in assessment.signals if s.direction == "bearish"]
    supporting = [s for s in assessment.signals if s.direction == "bullish"]
    assert opposing == []
    assert len(supporting) >= 3


def test_deteriorating_bars_produce_only_opposing_signals():
    assessment = _assess(_DETERIORATING_CLOSES, _book(bid=0.40), _DETERIORATING_RECENT_MIDS)
    assert assessment.state is MomentumState.REVERSING
    opposing = [s for s in assessment.signals if s.direction == "bearish"]
    supporting = [s for s in assessment.signals if s.direction == "bullish"]
    assert supporting == []
    assert len(opposing) >= 5


def test_conflicting_bars_produce_stable_evidence_below_the_weakening_threshold():
    assessment = _assess(_CONFLICTING_CLOSES, _book(bid=0.45), [])
    assert assessment.state is MomentumState.STABLE
    assert assessment.btc_assessment.weakening_score < 3  # below evaluate_momentum's own WEAKENING_THRESHOLD


# --- The 8 user-specified replay scenarios ------------------------------------

def test_scenario_1_minus_50pct_pnl_plus_strongly_improving_evidence_holds():
    book = _book(bid=0.40)
    assessment = _assess(_IMPROVING_CLOSES, book, _IMPROVING_RECENT_MIDS)
    position = _position(avg_fill_price=0.80)  # bid 0.40 vs entry 0.80 -> -50%
    decision = evaluate_dynamic_exit(position, book, assessment, profit_target_pct=0.20)
    assert decision.gross_pnl_pct == pytest.approx(-0.50)
    assert decision.eligible is False
    assert "p&l is context" in decision.reason.lower()


def test_scenario_2_minus_50pct_pnl_plus_strongly_deteriorating_evidence_exits():
    book = _book(bid=0.40)
    assessment = _assess(_DETERIORATING_CLOSES, book, _DETERIORATING_RECENT_MIDS)
    position = _position(avg_fill_price=0.80)  # same -50% P&L as scenario 1
    decision = evaluate_dynamic_exit(position, book, assessment, profit_target_pct=0.20)
    assert decision.gross_pnl_pct == pytest.approx(-0.50)
    assert decision.eligible is True


def test_scenario_3_plus_10pct_pnl_plus_deteriorating_evidence_exits():
    book = _book(bid=0.44)
    assessment = _assess(_DETERIORATING_CLOSES, book, _DETERIORATING_RECENT_MIDS)
    position = _position(avg_fill_price=0.40)  # bid 0.44 vs entry 0.40 -> +10%
    decision = evaluate_dynamic_exit(position, book, assessment, profit_target_pct=0.20)
    assert decision.gross_pnl_pct == pytest.approx(0.10)
    assert decision.eligible is True  # profitable, but exits anyway -- edge gone


def test_scenario_4_plus_20pct_pnl_plus_improving_evidence_holds():
    book = _book(bid=0.432)
    assessment = _assess(_IMPROVING_CLOSES, book, _IMPROVING_RECENT_MIDS)
    position = _position(avg_fill_price=0.36)  # bid 0.432 vs entry 0.36 -> +20%, exactly at the soft target
    decision = evaluate_dynamic_exit(position, book, assessment, profit_target_pct=0.20)
    assert decision.gross_pnl_pct == pytest.approx(0.20)
    assert decision.eligible is False  # soft target reached means nothing on its own


def test_scenario_5_small_loss_plus_improving_evidence_holds():
    book = _book(bid=0.38)
    assessment = _assess(_IMPROVING_CLOSES, book, _IMPROVING_RECENT_MIDS)
    position = _position(avg_fill_price=0.40)  # bid 0.38 vs entry 0.40 -> -5%
    decision = evaluate_dynamic_exit(position, book, assessment, profit_target_pct=0.20)
    assert decision.gross_pnl_pct == pytest.approx(-0.05)
    assert decision.eligible is False


def test_scenario_6_conflicting_btc_signals_holds():
    book = _book(bid=0.45)
    assessment = _assess(_CONFLICTING_CLOSES, book, [])
    position = _position(avg_fill_price=0.40)  # +12.5% -- irrelevant to the outcome either way
    decision = evaluate_dynamic_exit(position, book, assessment, profit_target_pct=0.20)
    assert decision.eligible is False
    assert "p&l is context" in decision.reason.lower()


def test_scenario_7_stale_feed_holds():
    book = _book(bid=0.55)
    stale_now = _bars(_IMPROVING_CLOSES)[-1].start_time + timedelta(seconds=400)  # past the 300s default threshold
    assessment = _assess(_IMPROVING_CLOSES, book, _IMPROVING_RECENT_MIDS, now=stale_now, max_bar_age_seconds=300.0)
    assert assessment.feed_status.status == "STALE"
    assert assessment.state is MomentumState.INSUFFICIENT_DATA
    position = _position(avg_fill_price=0.40)  # +37.5% -- a real system must NOT act on this stale-feed "gain"
    decision = evaluate_dynamic_exit(position, book, assessment, profit_target_pct=0.20)
    assert decision.eligible is False
    assert "insufficient" in decision.reason.lower()


def test_scenario_8_strong_positive_edge_holds_regardless_of_pnl():
    """The SAME improving evidence, replayed against deep profit, deep
    loss, and exact breakeven -- all three must HOLD identically,
    directly demonstrating P&L never independently moves the decision."""
    for avg_fill_price, bid in ((0.20, 0.90), (0.90, 0.20), (0.40, 0.40)):
        book = _book(bid=bid)
        assessment = _assess(_IMPROVING_CLOSES, book, _IMPROVING_RECENT_MIDS)
        position = _position(avg_fill_price=avg_fill_price)
        decision = evaluate_dynamic_exit(position, book, assessment, profit_target_pct=0.20)
        assert decision.eligible is False, f"avg_fill_price={avg_fill_price} bid={bid} pnl={decision.gross_pnl_pct}"
