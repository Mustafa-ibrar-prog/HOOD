"""Focused tests for trailing_stop.py -- the ONLY production exit
logic as of this round (a simple +20% profit trailing stop, replacing
the Coinbase-BTC-evidence-based dynamic exit entirely). Pure-function
tests against evaluate_trailing_stop() directly; the per-cycle
submit/loop functions (check_and_execute_trailing_stops) are covered
by test_polymarket_engine.py's end-to-end harness."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.polymarket.positions import OpenPosition
from src.polymarket.trailing_stop import ACTIVATION_MULTIPLE, evaluate_trailing_stop

_T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _position(**overrides) -> OpenPosition:
    defaults = dict(
        condition_id="c1", token_id="t1", outcome="YES", requested_size_usd=10.0,
        filled_shares=10.0, avg_fill_price=0.70, order_id="o1", client_order_id="co1",
        status="filled", opened_at=_T0, close_time=_T0 + timedelta(minutes=15),
    )
    defaults.update(overrides)
    return OpenPosition(**defaults)


# --- A: below +20% -> no trailing exit (not armed, HOLD) ------------------

def test_a_below_floor_holds_and_does_not_arm():
    position = _position(avg_fill_price=0.70)
    decision = evaluate_trailing_stop(position, executable_bid=0.75)  # floor is 0.84
    assert decision.action == "HOLD"
    assert decision.floor_price == pytest.approx(0.84)


# --- B: exactly +20% -> ARM, never an immediate sell -----------------------

def test_b_exactly_twenty_percent_arms_but_does_not_sell():
    position = _position(avg_fill_price=0.70)
    decision = evaluate_trailing_stop(position, executable_bid=0.84)
    assert decision.action == "ARM"
    assert decision.new_peak_price == pytest.approx(0.84)


# --- C: above +20% while unarmed also arms (overshoot) ---------------------

def test_c_overshooting_the_floor_while_unarmed_still_arms_not_sells():
    position = _position(avg_fill_price=0.70)
    decision = evaluate_trailing_stop(position, executable_bid=0.90)
    assert decision.action == "ARM"
    assert decision.new_peak_price == pytest.approx(0.90)


# --- D: once armed, rising further continues holding (updates peak) -------

def test_d_armed_position_rising_further_updates_peak_holds():
    position = _position(avg_fill_price=0.70, trailing_stop_armed=True, trailing_stop_peak_price=0.84)
    decision = evaluate_trailing_stop(position, executable_bid=0.90)
    assert decision.action == "UPDATE_PEAK"
    assert decision.new_peak_price == pytest.approx(0.90)

    position2 = _position(avg_fill_price=0.70, trailing_stop_armed=True, trailing_stop_peak_price=0.90)
    decision2 = evaluate_trailing_stop(position2, executable_bid=0.95)
    assert decision2.action == "UPDATE_PEAK"
    assert decision2.new_peak_price == pytest.approx(0.95)

    position3 = _position(avg_fill_price=0.70, trailing_stop_armed=True, trailing_stop_peak_price=0.95)
    decision3 = evaluate_trailing_stop(position3, executable_bid=1.00)
    assert decision3.action == "UPDATE_PEAK"
    assert decision3.new_peak_price == pytest.approx(1.00)


# --- E: falling back but still above the floor -> HOLD, peak untouched ----

def test_e_falling_back_above_floor_holds_without_changing_peak():
    position = _position(avg_fill_price=0.70, trailing_stop_armed=True, trailing_stop_peak_price=1.00)
    decision = evaluate_trailing_stop(position, executable_bid=0.90)
    assert decision.action == "HOLD"
    assert decision.new_peak_price is None  # nothing to persist -- peak stays 1.00


# --- F: falling back TO the floor -> FULL exit -----------------------------

def test_f_falling_back_to_floor_after_riding_higher_triggers_full_exit():
    position = _position(avg_fill_price=0.70, trailing_stop_armed=True, trailing_stop_peak_price=1.00)
    decision = evaluate_trailing_stop(position, executable_bid=0.84)
    assert decision.action == "SELL"
    assert decision.executable_bid == pytest.approx(0.84)


def test_f2_falling_below_floor_also_triggers_full_exit():
    position = _position(avg_fill_price=0.70, trailing_stop_armed=True, trailing_stop_peak_price=1.00)
    decision = evaluate_trailing_stop(position, executable_bid=0.80)
    assert decision.action == "SELL"


# --- G: the exact worked example from the governing spec -------------------

def test_g_worked_example_from_spec():
    # entry = 0.70, activation = 0.84
    position = _position(avg_fill_price=0.70)
    assert position.avg_fill_price * ACTIVATION_MULTIPLE == pytest.approx(0.84)

    d1 = evaluate_trailing_stop(position, executable_bid=0.84)
    assert d1.action == "ARM"
    position = replace(position, trailing_stop_armed=True, trailing_stop_peak_price=d1.new_peak_price)

    d2 = evaluate_trailing_stop(position, executable_bid=0.90)
    assert d2.action == "UPDATE_PEAK"
    position = replace(position, trailing_stop_peak_price=d2.new_peak_price)

    d3 = evaluate_trailing_stop(position, executable_bid=0.95)
    assert d3.action == "UPDATE_PEAK"
    position = replace(position, trailing_stop_peak_price=d3.new_peak_price)

    d4 = evaluate_trailing_stop(position, executable_bid=1.00)
    assert d4.action == "UPDATE_PEAK"
    position = replace(position, trailing_stop_peak_price=d4.new_peak_price)

    d5 = evaluate_trailing_stop(position, executable_bid=0.90)
    assert d5.action == "HOLD"

    d6 = evaluate_trailing_stop(position, executable_bid=0.84)
    assert d6.action == "SELL"


# --- H: no executable bid available -> always HOLD, never a guess ---------

def test_h_no_executable_bid_is_always_hold():
    position = _position(avg_fill_price=0.70)
    decision = evaluate_trailing_stop(position, executable_bid=None)
    assert decision.action == "HOLD"

    armed_position = _position(avg_fill_price=0.70, trailing_stop_armed=True, trailing_stop_peak_price=1.00)
    decision2 = evaluate_trailing_stop(armed_position, executable_bid=None)
    assert decision2.action == "HOLD"


# --- I: floor is always avg_fill_price * 1.20, never re-anchored to peak --

def test_i_floor_never_moves_even_after_riding_far_above_it():
    position = _position(avg_fill_price=0.70, trailing_stop_armed=True, trailing_stop_peak_price=2.00)
    decision = evaluate_trailing_stop(position, executable_bid=1.50)
    assert decision.floor_price == pytest.approx(0.84)  # unchanged regardless of peak
    assert decision.action == "HOLD"
