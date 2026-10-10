"""Focused tests for take_profit.py -- the ONLY production exit logic
as of this round (a fixed +5% take-profit target AND a fixed -20%
stop-loss, replacing the earlier +20% trailing stop entirely).
Pure-function tests against evaluate_take_profit() directly, plus a
restart-persistence test against the store; the per-cycle submit/loop
functions (check_and_execute_take_profits) are covered by
test_polymarket_engine.py's end-to-end harness."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.polymarket.positions import OpenPosition, PolymarketPositionStore
from src.polymarket.take_profit import (
    STOP_LOSS_MULTIPLE,
    TAKE_PROFIT_MULTIPLE,
    TRIGGER_STOP_LOSS,
    TRIGGER_TAKE_PROFIT,
    evaluate_take_profit,
)

_T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _position(**overrides) -> OpenPosition:
    defaults = dict(
        condition_id="c1", token_id="t1", outcome="YES", requested_size_usd=10.0,
        filled_shares=10.0, avg_fill_price=0.70, order_id="o1", client_order_id="co1",
        status="filled", opened_at=_T0, close_time=_T0 + timedelta(minutes=15),
    )
    defaults.update(overrides)
    return OpenPosition(**defaults)


# --- A: below +5% -> HOLD, never an early exit -----------------------------

def test_a_below_target_holds_never_an_early_exit():
    position = _position(avg_fill_price=0.70)  # target = 0.735
    decision = evaluate_take_profit(position, executable_bid=0.73)
    assert decision.action == "HOLD"
    assert decision.target_price == pytest.approx(0.735)


def test_a2_a_profitable_but_sub_target_position_still_holds():
    # Profitable (0.72 > 0.70 entry) but still below the +5% target
    # (0.735) -- must never sell "merely because it's profitable."
    position = _position(avg_fill_price=0.70)
    decision = evaluate_take_profit(position, executable_bid=0.72)
    assert decision.action == "HOLD"


# --- B: exactly at the target -> SELL --------------------------------------

def test_b_exactly_at_target_sells():
    position = _position(avg_fill_price=0.70)
    decision = evaluate_take_profit(position, executable_bid=0.735)
    assert decision.action == "SELL"
    assert decision.executable_bid == pytest.approx(0.735)


# --- C: above the target -> SELL (reaches OR exceeds) ----------------------

def test_c_above_target_also_sells():
    position = _position(avg_fill_price=0.70)
    decision = evaluate_take_profit(position, executable_bid=0.80)
    assert decision.action == "SELL"


# --- D: no executable bid -> always HOLD, never a guess --------------------

def test_d_no_executable_bid_is_always_hold():
    position = _position(avg_fill_price=0.70)
    decision = evaluate_take_profit(position, executable_bid=None)
    assert decision.action == "HOLD"


# --- E: the exact worked examples from the governing spec ------------------

@pytest.mark.parametrize(
    ("entry_price", "expected_target"),
    [(0.70, 0.735), (0.75, 0.7875), (0.80, 0.84)],
)
def test_e_worked_examples_from_spec(entry_price, expected_target):
    position = _position(avg_fill_price=entry_price)
    decision = evaluate_take_profit(position, executable_bid=entry_price)
    assert decision.target_price == pytest.approx(expected_target)


def test_e2_take_profit_multiple_is_exactly_1_05():
    assert TAKE_PROFIT_MULTIPLE == pytest.approx(1.05)


# --- H: the -20% stop-loss -------------------------------------------------

def test_h_exactly_at_stop_loss_sells():
    position = _position(avg_fill_price=0.70)  # stop_loss = 0.56
    # Use the exact computed stop_loss_price as the bid, never a hand-typed
    # literal -- 0.70 * 0.80 is not exactly representable in float, so a
    # literal 0.56 can land a hair above it and spuriously fail the
    # boundary check this test exists to cover.
    stop_loss_price = position.avg_fill_price * STOP_LOSS_MULTIPLE
    decision = evaluate_take_profit(position, executable_bid=stop_loss_price)
    assert decision.action == "SELL"
    assert decision.trigger == TRIGGER_STOP_LOSS
    assert decision.stop_loss_price == pytest.approx(0.56)


def test_h2_below_stop_loss_also_sells():
    position = _position(avg_fill_price=0.70)
    decision = evaluate_take_profit(position, executable_bid=0.40)
    assert decision.action == "SELL"
    assert decision.trigger == TRIGGER_STOP_LOSS


def test_h3_just_above_stop_loss_holds_not_yet_20_percent_down():
    # 0.57 is a loss from 0.70 entry, but not yet -20% (0.56) -- must hold.
    position = _position(avg_fill_price=0.70)
    decision = evaluate_take_profit(position, executable_bid=0.57)
    assert decision.action == "HOLD"
    assert decision.trigger is None


# --- I: worked examples for stop_loss_price, mirroring E -------------------

@pytest.mark.parametrize(
    ("entry_price", "expected_stop_loss"),
    [(0.70, 0.56), (0.75, 0.60), (0.80, 0.64)],
)
def test_i_worked_examples_for_stop_loss(entry_price, expected_stop_loss):
    position = _position(avg_fill_price=entry_price)
    decision = evaluate_take_profit(position, executable_bid=entry_price)
    assert decision.stop_loss_price == pytest.approx(expected_stop_loss)


def test_i2_stop_loss_multiple_is_exactly_0_80():
    assert STOP_LOSS_MULTIPLE == pytest.approx(0.80)


# --- J: strictly between both bounds -> HOLD, checking both bounds ---------

def test_j_strictly_between_stop_loss_and_target_holds():
    position = _position(avg_fill_price=0.70)  # stop_loss=0.56, target=0.735
    decision = evaluate_take_profit(position, executable_bid=0.65)
    assert decision.action == "HOLD"
    assert decision.trigger is None
    assert decision.stop_loss_price < 0.65 < decision.target_price


# --- K: the two SELL triggers are never confused for each other ------------

def test_k_take_profit_sell_reports_take_profit_trigger_not_stop_loss():
    position = _position(avg_fill_price=0.70)
    decision = evaluate_take_profit(position, executable_bid=0.80)
    assert decision.action == "SELL"
    assert decision.trigger == TRIGGER_TAKE_PROFIT


# --- L: the stop-loss persists across a restart, exactly like the target --

def test_l_stop_loss_price_persists_across_a_restart(tmp_path):
    path = tmp_path / "positions.json"
    store = PolymarketPositionStore(path)
    store.add_if_absent(_position(avg_fill_price=0.70, client_order_id="restart-2"))

    reopened_store = PolymarketPositionStore(path)
    reloaded = reopened_store.get("restart-2")
    assert reloaded is not None

    stop_loss_price = 0.70 * STOP_LOSS_MULTIPLE
    decision_before = evaluate_take_profit(_position(avg_fill_price=0.70), executable_bid=stop_loss_price)
    decision_after_restart = evaluate_take_profit(reloaded, executable_bid=stop_loss_price)
    assert decision_after_restart.stop_loss_price == pytest.approx(decision_before.stop_loss_price)
    assert decision_after_restart.action == decision_before.action == "SELL"
    assert decision_after_restart.trigger == TRIGGER_STOP_LOSS


# --- F: a full position exit sells the ACTUAL filled share count, never
# a partial or a re-derived quantity ---------------------------------------

def test_f_decision_always_carries_the_real_executable_bid_for_a_full_exit():
    position = _position(avg_fill_price=0.70, filled_shares=17.0)
    decision = evaluate_take_profit(position, executable_bid=0.90)
    assert decision.action == "SELL"
    # evaluate_take_profit itself doesn't place the order (that's
    # submit_take_profit_exit, covered end to end by
    # test_polymarket_engine.py), but it must always report the real
    # bid the submission will price against -- never a stale or
    # fabricated number.
    assert decision.executable_bid == pytest.approx(0.90)


# --- G: the target persists across a restart (it is re-derived from
# avg_fill_price, which is itself already persisted on the position --
# never a separate, independently-stored value that could drift) ----------

def test_g_target_price_persists_across_a_restart(tmp_path):
    path = tmp_path / "positions.json"
    store = PolymarketPositionStore(path)
    store.add_if_absent(_position(avg_fill_price=0.70, client_order_id="restart-1"))

    # A FRESH store instance pointed at the SAME file -- simulating a
    # process restart, never relying on in-memory state.
    reopened_store = PolymarketPositionStore(path)
    reloaded = reopened_store.get("restart-1")
    assert reloaded is not None

    decision_before = evaluate_take_profit(_position(avg_fill_price=0.70), executable_bid=0.735)
    decision_after_restart = evaluate_take_profit(reloaded, executable_bid=0.735)
    assert decision_after_restart.target_price == pytest.approx(decision_before.target_price)
    assert decision_after_restart.action == decision_before.action == "SELL"
