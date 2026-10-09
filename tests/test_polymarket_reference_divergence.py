"""Focused tests for reference_divergence.py -- the Coinbase-vs-
settlement-reference comparison added after this session's research
finding that Polymarket's 15-minute BTC Up/Down markets cite
Chainlink's BTC/USD Data Stream (not CF Benchmarks' BRTI) as their
resolution source. No live reference feed exists yet (Chainlink Data
Streams requires a paid subscription) -- these tests exercise the
comparison logic itself against hand-built BtcDirectionalAssessment
values, the same way test_polymarket_entry_confidence.py exercises
entry_confidence.py's pure functions directly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.polymarket.btc_entry_signal import assess_btc_entry_direction
from src.polymarket.btc_market_data import BtcPriceHistoryStore
from src.polymarket.reference_divergence import (
    STATUS_AGREEMENT,
    STATUS_DIVERGENCE,
    STATUS_REFERENCE_NEUTRAL,
    STATUS_REFERENCE_STALE,
    STATUS_REFERENCE_UNAVAILABLE,
    assess_divergence,
)
from src.strategy.evidence import MomentumState
from tests.test_polymarket_dynamic_exit_replay import (
    _REVERSING_CLOSES,
    _REVERSING_SEED,
    _feed,
    _strengthening_closes,
)

_PENALTY = 100.0


# --- A: no reference feed configured at all (today's default) -------------

def test_a_missing_reference_feed_is_a_zero_penalty_noop(tmp_path):
    coinbase_store = BtcPriceHistoryStore(tmp_path / "coinbase.json")
    end_t = _feed(coinbase_store, _strengthening_closes(), seed=5)
    now = end_t + timedelta(seconds=5)
    coinbase = assess_btc_entry_direction(
        coinbase_store.get_bars(interval_seconds=60, now=now), now=now, max_bar_age_seconds=300.0, feed_source="coinbase",
    )
    assert coinbase.direction == "bullish"

    result = assess_divergence(coinbase, None, divergence_penalty=_PENALTY)
    assert result.status == STATUS_REFERENCE_UNAVAILABLE
    assert result.confidence_penalty == 0.0


# --- B: reference feed configured but has no usable bars yet --------------

def test_b_reference_feed_with_no_bars_is_unavailable_zero_penalty(tmp_path):
    coinbase_store = BtcPriceHistoryStore(tmp_path / "coinbase.json")
    end_t = _feed(coinbase_store, _strengthening_closes(), seed=5)
    now = end_t + timedelta(seconds=5)
    coinbase = assess_btc_entry_direction(
        coinbase_store.get_bars(interval_seconds=60, now=now), now=now, max_bar_age_seconds=300.0, feed_source="coinbase",
    )

    reference = assess_btc_entry_direction([], now=now, max_bar_age_seconds=300.0, feed_source="reference")
    result = assess_divergence(coinbase, reference, divergence_penalty=_PENALTY)
    assert result.status == STATUS_REFERENCE_UNAVAILABLE
    assert result.confidence_penalty == 0.0


# --- C: reference feed is stale (bars exist but are too old) --------------

def test_c_stale_reference_feed_is_zero_penalty(tmp_path):
    coinbase_store = BtcPriceHistoryStore(tmp_path / "coinbase.json")
    end_t = _feed(coinbase_store, _strengthening_closes(), seed=5)
    now = end_t + timedelta(seconds=5)
    coinbase = assess_btc_entry_direction(
        coinbase_store.get_bars(interval_seconds=60, now=now), now=now, max_bar_age_seconds=300.0, feed_source="coinbase",
    )

    reference_store = BtcPriceHistoryStore(tmp_path / "reference.json")
    ref_end_t = _feed(reference_store, _strengthening_closes(), seed=5)
    # Evaluate the reference feed from far enough in the future that its
    # own newest bar reads STALE against a 300s max age.
    stale_now = ref_end_t + timedelta(seconds=301)
    reference = assess_btc_entry_direction(
        reference_store.get_bars(interval_seconds=60, now=stale_now), now=stale_now,
        max_bar_age_seconds=300.0, feed_source="reference",
    )
    assert reference.feed_status.status == "STALE"

    result = assess_divergence(coinbase, reference, divergence_penalty=_PENALTY)
    assert result.status == STATUS_REFERENCE_STALE
    assert result.confidence_penalty == 0.0


# --- D: reference feed is fresh but non-directional (neutral) -------------

def test_d_fresh_but_neutral_reference_feed_is_zero_penalty(tmp_path):
    coinbase_store = BtcPriceHistoryStore(tmp_path / "coinbase.json")
    end_t = _feed(coinbase_store, _strengthening_closes(), seed=5)
    now = end_t + timedelta(seconds=5)
    coinbase = assess_btc_entry_direction(
        coinbase_store.get_bars(interval_seconds=60, now=now), now=now, max_bar_age_seconds=300.0, feed_source="coinbase",
    )

    # Too few bars -- INSUFFICIENT_DATA on both framings -> neutral, but
    # NOT "unavailable" (feed_status reads FRESH on the one bar that exists).
    reference_store = BtcPriceHistoryStore(tmp_path / "reference.json")
    # A single sample, in a fully-closed prior minute bucket (so get_bars
    # actually returns it) and recent enough to read FRESH -- but far too
    # little data for a directional read (INSUFFICIENT_DATA -> neutral).
    reference_store.record_quote(50000.0, at=now - timedelta(seconds=65))
    reference = assess_btc_entry_direction(
        reference_store.get_bars(interval_seconds=60, now=now), now=now, max_bar_age_seconds=300.0, feed_source="reference",
    )
    assert reference.direction == "neutral"

    result = assess_divergence(coinbase, reference, divergence_penalty=_PENALTY)
    assert result.status == STATUS_REFERENCE_NEUTRAL
    assert result.confidence_penalty == 0.0


# --- E: Coinbase and reference AGREE -- zero penalty -----------------------

def test_e_coinbase_and_reference_agreement_is_zero_penalty(tmp_path):
    coinbase_store = BtcPriceHistoryStore(tmp_path / "coinbase.json")
    end_t = _feed(coinbase_store, _strengthening_closes(), seed=5)
    now = end_t + timedelta(seconds=5)
    coinbase = assess_btc_entry_direction(
        coinbase_store.get_bars(interval_seconds=60, now=now), now=now, max_bar_age_seconds=300.0, feed_source="coinbase",
    )
    assert coinbase.direction == "bullish"

    # Same fixture fed to the reference store -- same bullish read.
    reference_store = BtcPriceHistoryStore(tmp_path / "reference.json")
    _feed(reference_store, _strengthening_closes(), seed=5)
    reference = assess_btc_entry_direction(
        reference_store.get_bars(interval_seconds=60, now=now), now=now, max_bar_age_seconds=300.0, feed_source="reference",
    )
    assert reference.direction == "bullish"

    result = assess_divergence(coinbase, reference, divergence_penalty=_PENALTY)
    assert result.status == STATUS_AGREEMENT
    assert result.confidence_penalty == 0.0


# --- F: Coinbase and reference MATERIALLY DISAGREE -- bounded penalty ----

def test_f_coinbase_and_reference_disagreement_applies_penalty(tmp_path):
    coinbase_store = BtcPriceHistoryStore(tmp_path / "coinbase.json")
    end_t = _feed(coinbase_store, _strengthening_closes(), seed=5)
    now = end_t + timedelta(seconds=5)
    coinbase = assess_btc_entry_direction(
        coinbase_store.get_bars(interval_seconds=60, now=now), now=now, max_bar_age_seconds=300.0, feed_source="coinbase",
    )
    assert coinbase.direction == "bullish"

    # A DIFFERENT, bearish-reading fixture fed to the reference store,
    # aligned to end at the same `now`.
    reference_store = BtcPriceHistoryStore(tmp_path / "reference.json")
    ref_end_t = _feed(reference_store, _REVERSING_CLOSES, seed=_REVERSING_SEED)
    reference = assess_btc_entry_direction(
        reference_store.get_bars(interval_seconds=60, now=ref_end_t + timedelta(seconds=5)),
        now=ref_end_t + timedelta(seconds=5), max_bar_age_seconds=300.0, feed_source="reference",
    )
    # This fixture is pinned elsewhere as a WEAKENING/REVERSING read, not
    # necessarily entry-worthy bearish -- only proceed with the actual
    # disagreement assertion if it happens to read a hard opposite
    # direction; otherwise fall back to a synthetic, explicit disagreement
    # to keep this test deterministic regardless of fixture tuning drift.
    if reference.direction != "bearish":
        from src.polymarket.btc_entry_signal import BtcDirectionalAssessment

        reference = BtcDirectionalAssessment(
            direction="bearish", reason="synthetic bearish reference for test", neutral_reason_code=None,
            bullish_assessment=coinbase.bearish_assessment, bearish_assessment=coinbase.bullish_assessment,
            bullish_edge_points=-5.0, bearish_edge_points=5.0, bullish_entry_worthy=False, bearish_entry_worthy=True,
            feed_status=coinbase.feed_status,
        )

    result = assess_divergence(coinbase, reference, divergence_penalty=_PENALTY)
    assert result.status == STATUS_DIVERGENCE
    assert result.confidence_penalty == pytest.approx(-_PENALTY)
    # The penalty must always decrease confidence, never increase it,
    # regardless of the sign the caller happens to pass in.
    assert assess_divergence(coinbase, reference, divergence_penalty=-_PENALTY).confidence_penalty == pytest.approx(-_PENALTY)


# --- G: a hard divergence, folded through entry_confidence's own clamp,
# forces NO_TRADE regardless of how strong the base confidence was ----

def test_g_divergence_penalty_forces_no_trade_via_apply_historical_adjustment():
    from src.polymarket.trade_learning import apply_historical_adjustment

    # Even a maximal base confidence of 100 is driven to 0 by the
    # default -100 divergence penalty (a hard block, not a soft nudge).
    assert apply_historical_adjustment(100, -100.0) == 0
    assert apply_historical_adjustment(55, -100.0) == 0


# --- H: no lookahead -- a reference bar timestamped after `now` is never
# used to decide this cycle's divergence (same guarantee Coinbase's own
# feed already has -- see btc_market_data.BtcPriceHistoryStore.get_bars) --

def test_h_reference_feed_has_no_lookahead(tmp_path):
    reference_store = BtcPriceHistoryStore(tmp_path / "reference.json")
    end_t = _feed(reference_store, _strengthening_closes(), seed=5)
    decision_now = end_t - timedelta(hours=2)  # well before any of that data exists

    bars = reference_store.get_bars(interval_seconds=60, now=decision_now)
    assert bars == []

    reference = assess_btc_entry_direction(bars, now=decision_now, max_bar_age_seconds=300.0, feed_source="reference")
    assert reference.direction == "neutral"
    assert reference.momentum_state is None
