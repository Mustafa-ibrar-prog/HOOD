"""Tests for btc_entry_signal.py — Coinbase BTC evidence as the
PRIMARY entry-direction signal, replacing Polymarket YES-mid price
movement (strategy.py's old BtcMomentumStrategy, no longer the live
trigger — see engine.py's run_cycle()).

Three layers:
  - UNIT tests against assess_btc_entry_direction()/classify_btc_direction()
    directly, using the SAME pinned, already-verified real-bar fixtures
    test_polymarket_dynamic_exit_replay.py uses for the exit side (never
    a second, independently-tuned set of fixtures) — proves bullish/
    bearish/neutral/insufficient/stale detection reuses the existing
    evidence pipeline correctly.
  - UNIT tests against build_entry_candidate() directly — the
    Polymarket-quote mapping step, including the "thesis is directional
    but the book is unusable" case.
  - A couple of full end-to-end run_cycle() tests proving a Polymarket
    price move, by itself (zero BTC evidence fed), can never create an
    entry in either direction — the one property no unit test on
    btc_entry_signal.py alone could demonstrate, since that module
    never even looks at Polymarket data.

Never places a real order — every client/gateway here is paper mode or
a local fake.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.polymarket.btc_entry_signal import assess_btc_entry_direction, build_entry_candidate, classify_btc_direction
from src.polymarket.btc_intelligence import BtcMarketAssessment
from src.polymarket.btc_market_data import BtcPriceHistoryStore
from src.polymarket.engine import MarketHistory, run_cycle
from src.polymarket.gateway import PaperPolymarketGateway
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import BinaryMarket, BookLevel, OrderBookSnapshot
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import PolymarketPositionStore
from src.polymarket.risk import PolymarketRiskManager
from src.polymarket.settings import PolymarketSettings
from src.polymarket.state import DailyPnlStateStore
from src.polymarket.strategy import BtcMomentumStrategy
from src.strategy.evidence import MomentumAssessment, MomentumState
from tests.test_polymarket_dynamic_exit_replay import (
    _REVERSING_CLOSES,
    _REVERSING_SEED,
    _STABLE_CLOSES,
    _STABLE_SEED,
    _WEAKENING_CLOSES,
    _WEAKENING_SEED,
    _feed,
    _strengthening_closes,
)


def _market(**overrides) -> BinaryMarket:
    now = datetime.now(timezone.utc)
    defaults = dict(
        condition_id="c1", question="Will BTC be up?", token_id_yes="y", token_id_no="n",
        close_time=now + timedelta(minutes=10), fetched_at=now, yes_bid=0.60, yes_ask=0.62,
    )
    defaults.update(overrides)
    return BinaryMarket(**defaults)


# --- A/B/C/D/E: assess_btc_entry_direction() against real, pinned bars ------

def test_a_strong_bullish_evidence_yields_bullish_direction(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    end_t = _feed(store, _strengthening_closes(), seed=5)
    now = end_t + timedelta(seconds=5)
    bars = store.get_bars(interval_seconds=60, now=now)

    result = assess_btc_entry_direction(bars, now=now, max_bar_age_seconds=300.0, feed_source="test")

    assert result.direction == "bullish"
    assert result.outcome == "YES"
    assert result.bullish_entry_worthy is True
    assert result.edge_points > 0
    assert result.momentum_state is MomentumState.STRENGTHENING


def test_b_strong_bearish_evidence_yields_bearish_direction(tmp_path):
    """A persistent real DECLINE confirms a bearish thesis -- the exact
    same bars test_polymarket_dynamic_exit_replay.py pins as "STABLE
    (bullish-framed)" read STRENGTHENING once framed bearish, since a
    bullish thesis's own STABLE/WEAKENING state is just "a bearish
    thesis's evidence," reused rather than re-derived."""
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    end_t = _feed(store, _STABLE_CLOSES, seed=_STABLE_SEED)
    now = end_t + timedelta(seconds=5)
    bars = store.get_bars(interval_seconds=60, now=now)

    result = assess_btc_entry_direction(bars, now=now, max_bar_age_seconds=300.0, feed_source="test")

    assert result.direction == "bearish"
    assert result.outcome == "NO"
    assert result.bearish_entry_worthy is True
    assert result.edge_points > 0


def test_c_neutral_evidence_yields_no_entry(tmp_path):
    """Neither framing materially confirms its own thesis -- genuinely
    non-directional evidence, never guessed (the same real bars the
    exit side pins as producing a bullish-framed REVERSING / bearish-
    framed WEAKENING-but-not-STRENGTHENING split)."""
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    end_t = _feed(store, _REVERSING_CLOSES, seed=_REVERSING_SEED)
    now = end_t + timedelta(seconds=5)
    bars = store.get_bars(interval_seconds=60, now=now)

    result = assess_btc_entry_direction(bars, now=now, max_bar_age_seconds=300.0, feed_source="test")

    assert result.direction == "neutral"
    assert result.outcome is None
    assert result.neutral_reason_code == "neutral_btc_evidence"


def test_d_insufficient_evidence_yields_no_entry():
    """No bars fed at all -- the honest INSUFFICIENT_DATA default,
    never a guessed direction."""
    result = assess_btc_entry_direction([], now=datetime.now(timezone.utc), max_bar_age_seconds=300.0, feed_source="test")

    assert result.direction == "neutral"
    assert result.neutral_reason_code == "insufficient_btc_evidence"
    assert result.bullish_assessment.state is MomentumState.INSUFFICIENT_DATA
    assert result.bearish_assessment.state is MomentumState.INSUFFICIENT_DATA


def test_e_stale_data_yields_no_entry(tmp_path):
    """Real bars exist, materially bullish if read -- but they are
    older than max_bar_age_seconds, so the SAME stale-feed gate
    assess_btc_market() already uses (compute_feed_status) must zero
    them out here too, never letting a dead feed keep producing a
    confident entry signal."""
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    end_t = _feed(store, _strengthening_closes(), seed=5)
    stale_now = end_t + timedelta(seconds=600)  # well past the 300s default max age
    bars = store.get_bars(interval_seconds=60, now=stale_now)

    result = assess_btc_entry_direction(bars, now=stale_now, max_bar_age_seconds=300.0, feed_source="test")

    assert result.direction == "neutral"
    assert result.neutral_reason_code == "insufficient_btc_evidence"
    assert result.feed_status.status in ("STALE", "UNAVAILABLE")


def test_weak_single_signal_strengthening_does_not_qualify_as_entry_worthy():
    """Requirement: a single soft indicator must never be enough --
    mirrors evaluate_momentum's own 'a single soft signal is never
    enough' guarantee, applied on the entry side via
    min_strengthening_signals. A hand-built assessment reading
    STRENGTHENING with exactly ONE fired signal must not be worthy."""
    momentum = MomentumAssessment(state=MomentumState.STRENGTHENING, weakening_score=0, strengthening_score=1, signals=("trend_intact",))
    assessment = BtcMarketAssessment(state=MomentumState.STRENGTHENING, evidence_score=-1, btc_assessment=momentum, signals=())
    from src.polymarket.btc_entry_signal import DEFAULT_MIN_STRENGTHENING_SIGNALS_FOR_ENTRY

    direction, code, _ = classify_btc_direction(
        bullish_assessment=assessment, bearish_assessment=assessment, bullish_edge_points=1.0, bearish_edge_points=1.0,
        bullish_worthy=(assessment.signal_count >= DEFAULT_MIN_STRENGTHENING_SIGNALS_FOR_ENTRY), bearish_worthy=False,
    )
    assert direction == "neutral"  # 1 fired signal never clears the default-2 threshold on its own


# --- F: conflicting evidence (both framings simultaneously STRENGTHENING) --
# Exercised directly against classify_btc_direction() -- see that
# function's own docstring on why: the two framings' detector pairs are
# near-complementary by construction, so naturally reproducing a
# genuine BOTH-worthy case from real bars is intentionally rare; this
# proves the branch handles it correctly without depending on finding
# one.

def test_f_conflicting_evidence_yields_no_entry():
    bullish = BtcMarketAssessment(
        state=MomentumState.STRENGTHENING, evidence_score=-3,
        btc_assessment=MomentumAssessment(MomentumState.STRENGTHENING, 0, 3, ("trend_intact", "rsi_healthy_range")),
        signals=(),
    )
    bearish = BtcMarketAssessment(
        state=MomentumState.STRENGTHENING, evidence_score=-3,
        btc_assessment=MomentumAssessment(MomentumState.STRENGTHENING, 0, 3, ("trend_intact", "rsi_healthy_range")),
        signals=(),
    )
    direction, code, reason = classify_btc_direction(
        bullish_assessment=bullish, bearish_assessment=bearish, bullish_edge_points=3.0, bearish_edge_points=3.0,
        bullish_worthy=True, bearish_worthy=True,
    )
    assert direction == "neutral"
    assert code == "conflicting_btc_evidence"
    assert "conflicting" in reason.lower()


# --- build_entry_candidate(): the Polymarket-quote mapping step ------------

def _assessment(direction: str) -> object:
    """A minimal real BtcDirectionalAssessment for build_entry_candidate
    tests -- built from real bars so .selected_assessment is a genuine,
    fully-populated BtcMarketAssessment, not a hand-rolled stub."""
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "btc.json"
    store = BtcPriceHistoryStore(tmp)
    if direction == "bullish":
        end_t = _feed(store, _strengthening_closes(), seed=5)
    else:
        end_t = _feed(store, _WEAKENING_CLOSES, seed=_WEAKENING_SEED)
    now = end_t + timedelta(seconds=5)
    bars = store.get_bars(interval_seconds=60, now=now)
    return assess_btc_entry_direction(bars, now=now, max_bar_age_seconds=300.0, feed_source="test")


def test_bullish_thesis_builds_a_yes_candidate_at_the_real_ask():
    assessment = _assessment("bullish")
    market = _market(yes_bid=0.60, yes_ask=0.62)
    candidate = build_entry_candidate(market, assessment, size_usd=5.0)
    assert candidate is not None
    assert candidate.thesis.outcome == "YES"
    assert candidate.suggested_entry_price == 0.62
    assert candidate.suggested_size_usd == 5.0


def test_bearish_thesis_builds_a_no_candidate_from_the_real_bid():
    assessment = _assessment("bearish")
    market = _market(yes_bid=0.60, yes_ask=0.62)
    candidate = build_entry_candidate(market, assessment, size_usd=5.0)
    assert candidate is not None
    assert candidate.thesis.outcome == "NO"
    assert candidate.suggested_entry_price == round(1 - 0.60, 4)
    assert candidate.suggested_size_usd == 5.0


def test_neutral_direction_never_builds_a_candidate():
    neutral = assess_btc_entry_direction([], now=datetime.now(timezone.utc), max_bar_age_seconds=300.0)
    market = _market(yes_bid=0.60, yes_ask=0.62)
    assert build_entry_candidate(market, neutral, size_usd=5.0) is None


def test_i_bullish_thesis_with_unusable_yes_book_yields_no_candidate():
    """Requirement I: BTC evidence confirms bullish, but the YES side
    has no two-sided quote yet -- never guess a price, never fall back
    to the other side."""
    assessment = _assessment("bullish")
    market = _market(yes_bid=0.60, yes_ask=None)  # no ask to buy YES at
    assert build_entry_candidate(market, assessment, size_usd=5.0) is None


def test_j_bearish_thesis_with_unusable_no_book_yields_no_candidate():
    """Requirement J: BTC evidence confirms bearish, but there's no
    yes_bid to derive the NO entry price from."""
    assessment = _assessment("bearish")
    market = _market(yes_bid=None, yes_ask=0.62)
    assert build_entry_candidate(market, assessment, size_usd=5.0) is None


# --- G/H: a Polymarket price move, alone, can never create an entry -------
# Full run_cycle() end to end, with ZERO BTC bars fed (the harness's
# btc_price_store is always empty here) -- only Polymarket's own
# yes_bid/yes_ask/history.mids move; btc_entry_signal.py never reads
# any of it, so the result must be "no entry" regardless of direction.

def _engine_harness(tmp_path: Path, market: BinaryMarket):
    from tests.test_polymarket_engine import _FakeClient

    settings = PolymarketSettings.from_env(env={"POLYMARKET_LOG_DIR": str(tmp_path)})
    client = _FakeClient(market)
    strategy = BtcMomentumStrategy()
    risk = PolymarketRiskManager(settings)
    logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    gateway = PaperPolymarketGateway(settings, logger)
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    history = MarketHistory()
    btc_price_store = BtcPriceHistoryStore(tmp_path / "btc.json")  # deliberately never fed
    return dict(
        settings=settings, client=client, strategy=strategy, risk_manager=risk, gateway=gateway,
        decision_logger=logger, state_store=state_store, position_store=position_store,
        pending_store=pending_store, history=history, btc_price_store=btc_price_store,
    )


def test_g_polymarket_price_rising_alone_never_triggers_a_yes_entry(tmp_path):
    """The exact OLD trigger (YES mid .50 -> .56-ish, a clear rising
    move) with zero Coinbase BTC evidence fed -- must NOT enter."""
    market = _market(yes_bid=0.78, yes_ask=0.80)  # would have clearly qualified under the old strategy
    harness = _engine_harness(tmp_path, market)
    harness["history"].observe(market)
    harness["history"].mids = [0.50, 0.60, 0.70]  # a big rising Polymarket move, on its own

    report = run_cycle(**harness)

    assert report.entered is False
    assert harness["position_store"].load() == []


def test_h_polymarket_price_falling_alone_never_triggers_a_no_entry(tmp_path):
    """The symmetric case: YES mid falling (.50 -> .36-ish) alone must
    not trigger a NO entry either."""
    market = _market(yes_bid=0.35, yes_ask=0.37)
    harness = _engine_harness(tmp_path, market)
    harness["history"].observe(market)
    harness["history"].mids = [0.50, 0.45, 0.40]  # a big falling Polymarket move, on its own

    report = run_cycle(**harness)

    assert report.entered is False
    assert harness["position_store"].load() == []


# --- O: entry sizing is confidence-based and bounded $5-$20, end to end ----

def test_o_entry_size_is_confidence_based_and_within_bounds(tmp_path):
    """This fixture's own edge_points(+2)/fired_signal_count(2) maps to
    the MINIMUM confidence bucket (see entry_confidence.py) -- the $5
    floor for any APPROVED trade, never $0 (which would mean no trade
    at all) and never above the $20 hard ceiling."""
    market = _market(yes_bid=0.78, yes_ask=0.80)
    settings = PolymarketSettings.from_env(env={"POLYMARKET_LOG_DIR": str(tmp_path)})
    from tests.test_polymarket_engine import _FakeClient

    client = _FakeClient(market)
    strategy = BtcMomentumStrategy()
    risk = PolymarketRiskManager(settings)
    logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    gateway = PaperPolymarketGateway(settings, logger)
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    history = MarketHistory()
    btc_price_store = BtcPriceHistoryStore(tmp_path / "btc.json")
    end_t = _feed(btc_price_store, _strengthening_closes(), seed=5)
    now = end_t + timedelta(seconds=5)

    report = run_cycle(
        settings=settings, client=client, strategy=strategy, risk_manager=risk, gateway=gateway,
        decision_logger=logger, state_store=state_store, position_store=position_store,
        pending_store=pending_store, history=history, btc_price_store=btc_price_store, now=now,
    )

    assert report.entered is True
    position = position_store.load()[0]
    assert position.requested_size_usd == pytest.approx(5.0)


# --- P: the risk manager remains the final authority -- a confidence-
# approved size can still be blocked by an unrelated, pre-existing risk
# control (here: MAX_BET_SIZE configured below what confidence
# approved). Confidence sizing must never bypass risk.py. -------------

def test_p_risk_manager_still_blocks_a_confidence_approved_size(tmp_path):
    market = _market(yes_bid=0.78, yes_ask=0.80)
    # This fixture's confidence-recommended size is $5.00 (see test O) --
    # configuring MAX_BET_SIZE below that must still block the trade,
    # exactly as it would for any other size.
    settings = PolymarketSettings.from_env(
        env={"POLYMARKET_LOG_DIR": str(tmp_path), "POLYMARKET_MAX_BET_USD": "4.00"},
    )
    from tests.test_polymarket_engine import _FakeClient

    client = _FakeClient(market)
    strategy = BtcMomentumStrategy()
    risk = PolymarketRiskManager(settings)
    logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    gateway = PaperPolymarketGateway(settings, logger)
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    history = MarketHistory()
    btc_price_store = BtcPriceHistoryStore(tmp_path / "btc.json")
    end_t = _feed(btc_price_store, _strengthening_closes(), seed=5)
    now = end_t + timedelta(seconds=5)

    report = run_cycle(
        settings=settings, client=client, strategy=strategy, risk_manager=risk, gateway=gateway,
        decision_logger=logger, state_store=state_store, position_store=position_store,
        pending_store=pending_store, history=history, btc_price_store=btc_price_store, now=now,
    )

    assert report.entered is False
    assert position_store.load() == []


# --- P2: a corrupted completed-trade learning store fails SAFE -- the
# cycle still runs and still enters at BASE confidence (TASK 2's
# required "corrupted learning store fails safely" behavior), never a
# crash and never a silently-fabricated adjustment. ------------------

def test_p2_corrupted_learning_store_fails_safe_and_cycle_still_runs(tmp_path):
    from src.polymarket.trade_learning import CompletedTradeStore

    market = _market(yes_bid=0.78, yes_ask=0.80)
    settings = PolymarketSettings.from_env(env={"POLYMARKET_LOG_DIR": str(tmp_path)})
    from tests.test_polymarket_engine import _FakeClient

    client = _FakeClient(market)
    strategy = BtcMomentumStrategy()
    risk = PolymarketRiskManager(settings)
    logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    gateway = PaperPolymarketGateway(settings, logger)
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    history = MarketHistory()
    btc_price_store = BtcPriceHistoryStore(tmp_path / "btc.json")
    end_t = _feed(btc_price_store, _strengthening_closes(), seed=5)
    now = end_t + timedelta(seconds=5)

    trades_path = tmp_path / "completed_trades.json"
    trades_path.write_text("{not valid json")
    trade_store = CompletedTradeStore(trades_path)

    report = run_cycle(
        settings=settings, client=client, strategy=strategy, risk_manager=risk, gateway=gateway,
        decision_logger=logger, state_store=state_store, position_store=position_store,
        pending_store=pending_store, history=history, btc_price_store=btc_price_store, now=now,
        trade_store=trade_store,
    )

    assert report.entered is True  # the corrupted store never blocks or crashes the cycle
    position = position_store.load()[0]
    assert position.requested_size_usd == pytest.approx(5.0)  # base confidence governs; no adjustment applied


# --- Q: no lookahead -- only data available as of `now` is ever used -------

def test_q_bars_fed_after_now_are_never_used_for_the_decision(tmp_path):
    """BtcPriceHistoryStore.get_bars(now=...) already refuses to return
    a still-in-progress or future bucket (see btc_market_data.py) --
    this proves that guarantee holds for the ENTRY path specifically:
    materially bullish ticks timestamped entirely AFTER `decision_now`
    must never influence a decision made AT `decision_now`."""
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    end_t = _feed(store, _strengthening_closes(), seed=5)  # ticks span roughly [end_t - 45min, end_t]
    decision_now = end_t - timedelta(hours=2)  # well before any of that data exists

    bars = store.get_bars(interval_seconds=60, now=decision_now)
    assert bars == []  # nothing fed is actually <= decision_now yet

    result = assess_btc_entry_direction(bars, now=decision_now, max_bar_age_seconds=300.0, feed_source="test")
    assert result.direction == "neutral"
    assert result.neutral_reason_code == "insufficient_btc_evidence"
