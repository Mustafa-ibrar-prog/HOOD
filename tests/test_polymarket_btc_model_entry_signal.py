"""Focused tests for btc_model_entry_signal.py -- the ONLY production
entry-direction decision as of this round. Pure-function tests
against assess_model_entry() directly, using hand-built
BtcDirectionPrediction/OrderBookSnapshot values -- no run_cycle
needed (see test_polymarket_engine.py for end-to-end wiring)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.polymarket.btc_direction_model import BtcDirectionPrediction
from src.polymarket.btc_model_entry_signal import assess_model_entry
from src.polymarket.models import BookLevel, OrderBookSnapshot

_T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _prediction(*, up: float, is_trained: bool = True) -> BtcDirectionPrediction:
    return BtcDirectionPrediction(
        predicted_up_probability=up, predicted_down_probability=1.0 - up,
        favored_outcome=("UP" if up > 0.5 else "DOWN" if up < 0.5 else None), is_trained=is_trained,
        feature_timestamp=_T0, time_remaining=300.0, price_to_beat=65_000.0, current_btc_price=65_100.0,
        model_version="test", data_source="synthetic",
    )


def _book(*, bid: float, ask: float) -> OrderBookSnapshot:
    return OrderBookSnapshot(token_id="t", bids=(BookLevel(bid, 1000.0),), asks=(BookLevel(ask, 1000.0),), fetched_at=_T0)


# --- A: the exact worked example from this round's governing spec ----------

def test_a_the_governing_spec_worked_example():
    # Model UP=0.68, Polymarket UP ask=0.57 (mid 0.56) -> net edge ~0.11
    prediction = _prediction(up=0.68)
    up_book = _book(bid=0.55, ask=0.57)
    down_book = _book(bid=0.42, ask=0.44)
    signal = assess_model_entry(
        prediction=prediction, up_order_book=up_book, down_order_book=down_book,
        has_minimum_feature_data=True, min_model_edge=0.05, fee_pct=0.0, slippage_pct=0.0,
    )
    assert signal.decision == "TRADE"
    assert signal.outcome == "YES"
    assert signal.up_edge == pytest.approx(0.68 - 0.57)
    assert signal.executable_entry_price == pytest.approx(0.57)


def test_a2_model_up_052_market_up_051_is_no_trade():
    prediction = _prediction(up=0.52)
    up_book = _book(bid=0.50, ask=0.51)
    down_book = _book(bid=0.48, ask=0.49)
    signal = assess_model_entry(
        prediction=prediction, up_order_book=up_book, down_order_book=down_book,
        has_minimum_feature_data=True, min_model_edge=0.05,
    )
    assert signal.decision == "NO_TRADE"
    assert signal.outcome is None


def test_a3_model_down_070_market_down_055_is_eligible():
    prediction = _prediction(up=0.30)  # DOWN = 0.70
    up_book = _book(bid=0.44, ask=0.46)
    down_book = _book(bid=0.53, ask=0.55)
    signal = assess_model_entry(
        prediction=prediction, up_order_book=up_book, down_order_book=down_book,
        has_minimum_feature_data=True, min_model_edge=0.05,
    )
    assert signal.decision == "TRADE"
    assert signal.outcome == "NO"
    assert signal.executable_entry_price == pytest.approx(0.55)


# --- B: hard gates (independent of min_model_edge) --------------------------

def test_b_untrained_model_is_always_no_trade():
    prediction = _prediction(up=0.99, is_trained=False)
    signal = assess_model_entry(
        prediction=prediction, up_order_book=_book(bid=0.10, ask=0.12), down_order_book=_book(bid=0.86, ask=0.88),
        has_minimum_feature_data=True, min_model_edge=0.0,
    )
    assert signal.decision == "NO_TRADE"
    assert "untrained" in signal.reason


def test_b2_insufficient_feature_data_is_always_no_trade():
    prediction = _prediction(up=0.99)
    signal = assess_model_entry(
        prediction=prediction, up_order_book=_book(bid=0.10, ask=0.12), down_order_book=_book(bid=0.86, ask=0.88),
        has_minimum_feature_data=False, min_model_edge=0.0,
    )
    assert signal.decision == "NO_TRADE"
    assert "insufficient" in signal.reason.lower()


def test_b3_missing_up_book_is_no_trade():
    prediction = _prediction(up=0.68)
    signal = assess_model_entry(
        prediction=prediction, up_order_book=None, down_order_book=_book(bid=0.42, ask=0.44),
        has_minimum_feature_data=True, min_model_edge=0.05,
    )
    assert signal.decision == "NO_TRADE"
    assert signal.outcome is None


def test_b4_missing_down_book_is_no_trade():
    prediction = _prediction(up=0.68)
    signal = assess_model_entry(
        prediction=prediction, up_order_book=_book(bid=0.55, ask=0.57), down_order_book=None,
        has_minimum_feature_data=True, min_model_edge=0.05,
    )
    assert signal.decision == "NO_TRADE"
    assert signal.outcome is None


def test_b5_one_sided_book_with_no_bid_is_no_trade():
    prediction = _prediction(up=0.68)
    one_sided = OrderBookSnapshot(token_id="t", bids=(), asks=(BookLevel(0.57, 1000.0),), fetched_at=_T0)
    signal = assess_model_entry(
        prediction=prediction, up_order_book=one_sided, down_order_book=_book(bid=0.42, ask=0.44),
        has_minimum_feature_data=True, min_model_edge=0.05,
    )
    assert signal.decision == "NO_TRADE"


# --- C: minimum edge filter ---------------------------------------------------

def test_c_insufficient_edge_is_no_trade():
    prediction = _prediction(up=0.60)
    signal = assess_model_entry(
        prediction=prediction, up_order_book=_book(bid=0.58, ask=0.59), down_order_book=_book(bid=0.40, ask=0.41),
        has_minimum_feature_data=True, min_model_edge=0.10,  # raw edge is only 0.01
    )
    assert signal.decision == "NO_TRADE"
    assert "edge too small" in signal.reason


def test_c2_exact_threshold_boundary_is_inclusive():
    # min_model_edge derived from the SAME arithmetic assess_model_entry
    # itself does, never a separately hand-typed literal -- 0.60 - 0.50
    # is not exactly 0.10 in float, so a literal 0.10 could land a hair
    # on the wrong side of this exact boundary and spuriously fail.
    prediction = _prediction(up=0.60)
    up_book = _book(bid=0.49, ask=0.50)
    edge = prediction.predicted_up_probability - up_book.best_ask
    signal = assess_model_entry(
        prediction=prediction, up_order_book=up_book, down_order_book=_book(bid=0.49, ask=0.50),
        has_minimum_feature_data=True, min_model_edge=edge,
    )
    assert signal.decision == "TRADE"
    assert signal.outcome == "YES"


# --- D: spread/fee/slippage-aware edge ---------------------------------------

def test_d_fee_and_slippage_reduce_the_effective_edge():
    prediction = _prediction(up=0.60)
    up_book = _book(bid=0.49, ask=0.50)  # raw edge 0.10
    cheap = assess_model_entry(
        prediction=prediction, up_order_book=up_book, down_order_book=_book(bid=0.49, ask=0.50),
        has_minimum_feature_data=True, min_model_edge=0.05, fee_pct=0.0, slippage_pct=0.0,
    )
    expensive = assess_model_entry(
        prediction=prediction, up_order_book=up_book, down_order_book=_book(bid=0.49, ask=0.50),
        has_minimum_feature_data=True, min_model_edge=0.05, fee_pct=0.03, slippage_pct=0.03,
    )
    assert cheap.decision == "TRADE"
    assert expensive.decision == "NO_TRADE"  # the same raw edge, but costs eat it below the minimum
    assert expensive.up_edge == pytest.approx(cheap.up_edge - 0.06)


def test_d2_a_tiny_edge_that_disappears_after_costs_is_no_trade():
    prediction = _prediction(up=0.55)
    up_book = _book(bid=0.53, ask=0.54)  # raw edge 0.01
    signal = assess_model_entry(
        prediction=prediction, up_order_book=up_book, down_order_book=_book(bid=0.45, ask=0.46),
        has_minimum_feature_data=True, min_model_edge=0.0, fee_pct=0.005, slippage_pct=0.01,
    )
    assert signal.decision == "NO_TRADE"  # 0.01 - 0.015 < 0 -- negative net edge


def test_d3_executable_entry_price_is_the_real_ask_never_the_model_or_market_probability():
    prediction = _prediction(up=0.68)
    up_book = _book(bid=0.55, ask=0.57)
    signal = assess_model_entry(
        prediction=prediction, up_order_book=up_book, down_order_book=_book(bid=0.42, ask=0.44),
        has_minimum_feature_data=True, min_model_edge=0.05,
    )
    assert signal.executable_entry_price == pytest.approx(0.57)
    assert signal.executable_entry_price != pytest.approx(prediction.predicted_up_probability)
    assert signal.executable_entry_price != pytest.approx(signal.market_up_probability)


# --- E: both sides qualifying picks the larger edge, never both -------------

def test_e_when_both_sides_qualify_the_larger_edge_wins():
    prediction = _prediction(up=0.80)  # DOWN = 0.20, won't realistically qualify, but test the tie-break rule directly
    # Construct an artificial case where both edges are positive by using very cheap books on both sides.
    up_book = _book(bid=0.09, ask=0.10)
    down_book = _book(bid=0.09, ask=0.10)
    signal = assess_model_entry(
        prediction=prediction, up_order_book=up_book, down_order_book=down_book,
        has_minimum_feature_data=True, min_model_edge=0.05,
    )
    assert signal.decision == "TRADE"
    assert signal.outcome == "YES"  # up_edge (0.70) > down_edge (0.10) -- the larger one wins
    assert signal.up_edge > signal.down_edge


# --- F: logging vocabulary ---------------------------------------------------

def test_f_to_log_fields_carries_the_required_vocabulary():
    prediction = _prediction(up=0.68)
    signal = assess_model_entry(
        prediction=prediction, up_order_book=_book(bid=0.55, ask=0.57), down_order_book=_book(bid=0.42, ask=0.44),
        has_minimum_feature_data=True, min_model_edge=0.05,
    )
    fields = signal.to_log_fields()
    for key in ("MARKET_UP_PROBABILITY", "MARKET_DOWN_PROBABILITY", "UP_EDGE", "DOWN_EDGE", "SELECTED_OUTCOME",
                "EXECUTABLE_ENTRY_PRICE", "DECISION", "REASON"):
        assert key in fields
