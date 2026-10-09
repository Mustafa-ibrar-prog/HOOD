"""Focused tests for entry_confidence.py (TASK 1) -- the deterministic
0-100 confidence score that decides WHETHER to enter and HOW MUCH to
risk for a Coinbase-driven entry candidate (see btc_entry_signal.py).

These are pure-function tests against hand-picked (direction,
edge_points, fired_signal_count) inputs -- no run_cycle() harness
needed, since compute_base_confidence/confidence_bucket/
recommended_size_usd/assess_confidence take only primitives.
"""

from __future__ import annotations

import pytest

from src.polymarket.entry_confidence import (
    MAX_APPROVED_TRADE_SIZE_USD,
    MIN_APPROVED_TRADE_SIZE_USD,
    assess_confidence,
    compute_base_confidence,
    confidence_bucket,
    recommended_size_usd,
)


# --- A: weak bullish -> NO_TRADE or the $5 floor, never in between ---------

def test_a_weak_bullish_is_no_trade_or_minimum_floor():
    result = assess_confidence(direction="bullish", edge_points=2, fired_signal_count=2)
    assert result.base_confidence == 55
    assert result.bucket == "MINIMUM"
    assert result.recommended_size_usd == pytest.approx(5.0)
    assert result.approved is True


# --- B: moderate bullish -> $7.50 -------------------------------------------

def test_b_moderate_bullish_is_seven_fifty():
    result = assess_confidence(direction="bullish", edge_points=3, fired_signal_count=2)
    assert result.base_confidence == 60
    assert result.bucket == "MODERATE"
    assert result.recommended_size_usd == pytest.approx(7.5)


# --- C: strong bullish -> $10.00 --------------------------------------------

def test_c_strong_bullish_is_ten():
    result = assess_confidence(direction="bullish", edge_points=4, fired_signal_count=3)
    assert result.base_confidence == 70
    assert result.bucket == "STRONG"
    assert result.recommended_size_usd == pytest.approx(10.0)


# --- D: very strong bullish -> $15.00 ---------------------------------------

def test_d_very_strong_bullish_is_fifteen():
    result = assess_confidence(direction="bullish", edge_points=5, fired_signal_count=4)
    assert result.base_confidence == 80
    assert result.bucket == "VERY_STRONG"
    assert result.recommended_size_usd == pytest.approx(15.0)


# --- E: extreme bullish -> $20.00 (the hard ceiling) ------------------------

def test_e_extreme_bullish_is_twenty():
    result = assess_confidence(direction="bullish", edge_points=6, fired_signal_count=5)
    assert result.base_confidence == 90
    assert result.bucket == "EXTREME"
    assert result.recommended_size_usd == pytest.approx(20.0)


# --- F: bearish behaves exactly symmetrically to bullish --------------------

@pytest.mark.parametrize(
    ("edge_points", "fired_signal_count", "expected_confidence", "expected_bucket", "expected_size"),
    [
        (2, 2, 55, "MINIMUM", 5.0),
        (3, 2, 60, "MODERATE", 7.5),
        (4, 3, 70, "STRONG", 10.0),
        (5, 4, 80, "VERY_STRONG", 15.0),
        (6, 5, 90, "EXTREME", 20.0),
    ],
)
def test_f_bearish_is_symmetric_to_bullish(edge_points, fired_signal_count, expected_confidence, expected_bucket, expected_size):
    bullish = assess_confidence(direction="bullish", edge_points=edge_points, fired_signal_count=fired_signal_count)
    bearish = assess_confidence(direction="bearish", edge_points=edge_points, fired_signal_count=fired_signal_count)
    assert bearish.base_confidence == bullish.base_confidence == expected_confidence
    assert bearish.bucket == bullish.bucket == expected_bucket
    assert bearish.recommended_size_usd == bullish.recommended_size_usd == pytest.approx(expected_size)


# --- G: neutral direction is always NO_TRADE / $0, regardless of inputs ----

def test_g_neutral_direction_is_always_no_trade():
    result = assess_confidence(direction="neutral", edge_points=99, fired_signal_count=99)
    assert result.base_confidence == 0
    assert result.bucket == "NO_TRADE"
    assert result.recommended_size_usd == 0.0
    assert result.approved is False


# --- H: "conflicting"/"stale" BTC evidence is represented upstream as
# direction == "neutral" (see btc_entry_signal.classify_btc_direction) --
# confirming that collapses to the exact same NO_TRADE outcome here. ---

def test_h_conflicting_and_stale_evidence_collapse_to_neutral_no_trade():
    for edge_points, fired_signal_count in [(0, 0), (1, 0), (0, 3)]:
        result = assess_confidence(direction="neutral", edge_points=edge_points, fired_signal_count=fired_signal_count)
        assert result.bucket == "NO_TRADE"
        assert result.recommended_size_usd == 0.0


# --- I: confidence is clamped at 100 -- size never exceeds the $20 ceiling --

def test_i_confidence_clamped_at_100_never_exceeds_twenty_dollars():
    result = assess_confidence(direction="bullish", edge_points=1000, fired_signal_count=1000)
    assert result.base_confidence == 100
    assert result.recommended_size_usd == pytest.approx(MAX_APPROVED_TRADE_SIZE_USD)
    assert result.recommended_size_usd <= 20.0


# --- J: any approved (non-zero) size is never below the $5 floor -----------

@pytest.mark.parametrize("confidence", list(range(0, 101)))
def test_j_approved_size_never_below_five_dollars(confidence):
    size = recommended_size_usd(confidence)
    assert size == 0.0 or size >= MIN_APPROVED_TRADE_SIZE_USD


# --- K: the 50/60/70/80/90 bucket boundaries are exact ----------------------

@pytest.mark.parametrize(
    ("confidence", "expected_bucket", "expected_size"),
    [
        (0, "NO_TRADE", 0.0),
        (49, "NO_TRADE", 0.0),
        (50, "MINIMUM", 5.0),
        (59, "MINIMUM", 5.0),
        (60, "MODERATE", 7.5),
        (69, "MODERATE", 7.5),
        (70, "STRONG", 10.0),
        (79, "STRONG", 10.0),
        (80, "VERY_STRONG", 15.0),
        (89, "VERY_STRONG", 15.0),
        (90, "EXTREME", 20.0),
        (100, "EXTREME", 20.0),
    ],
)
def test_k_bucket_boundaries_are_exact(confidence, expected_bucket, expected_size):
    assert confidence_bucket(confidence) == expected_bucket
    assert recommended_size_usd(confidence) == pytest.approx(expected_size)


# --- L: compute_base_confidence never returns outside [0, 100] -------------

@pytest.mark.parametrize(
    ("direction", "edge_points", "fired_signal_count"),
    [("bullish", -1000, 0), ("bearish", -1000, -1000), ("bullish", 1000, 1000)],
)
def test_l_base_confidence_always_within_bounds(direction, edge_points, fired_signal_count):
    confidence = compute_base_confidence(direction=direction, edge_points=edge_points, fired_signal_count=fired_signal_count)
    assert 0 <= confidence <= 100
