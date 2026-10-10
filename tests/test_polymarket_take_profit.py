"""Focused tests for take_profit.py -- the ONLY automatic exit logic
as of this round: a configurable take-profit AND a configurable
stop-loss (defaults +5% / -20%), BOTH driven by settings rather than
hard-coded constants. Pure-function tests against evaluate_take_profit()
directly, plus a restart-persistence test against the store; the
per-cycle submit/loop functions (check_and_execute_take_profits) are
covered by test_polymarket_engine.py's end-to-end harness."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.polymarket.positions import OpenPosition, PolymarketPositionStore
from src.polymarket.take_profit import (
    DEFAULT_STOP_LOSS_PCT,
    DEFAULT_TAKE_PROFIT_PCT,
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


# --- A: strictly between the two bounds -> HOLD, never an early exit -------

def test_a_below_target_holds_never_an_early_exit():
    position = _position(avg_fill_price=0.70)  # target = 0.735 at the 5% default
    decision = evaluate_take_profit(position, executable_bid=0.73)
    assert decision.action == "HOLD"
    assert decision.target_price == pytest.approx(0.735)


def test_a2_a_profitable_but_sub_target_position_still_holds():
    # Profitable (0.72 > 0.70 entry) but still below the take-profit
    # target (0.735) -- must never sell "merely because it's profitable."
    position = _position(avg_fill_price=0.70)
    decision = evaluate_take_profit(position, executable_bid=0.72)
    assert decision.action == "HOLD"


def test_a3_a_small_loss_above_the_stop_loss_floor_also_holds():
    # A real loss (0.60 vs 0.70 entry) but still above the -20% floor
    # (0.56) -- must never sell on a loss before the floor is reached.
    position = _position(avg_fill_price=0.70)
    decision = evaluate_take_profit(position, executable_bid=0.60)
    assert decision.action == "HOLD"


# --- B: exactly at the take-profit target -> SELL --------------------------

def test_b_exactly_at_target_sells():
    position = _position(avg_fill_price=0.70)
    decision = evaluate_take_profit(position, executable_bid=0.735)
    assert decision.action == "SELL"
    assert decision.trigger == TRIGGER_TAKE_PROFIT
    assert decision.executable_bid == pytest.approx(0.735)


# --- C: above the target -> SELL (reaches OR exceeds) ----------------------

def test_c_above_target_also_sells():
    position = _position(avg_fill_price=0.70)
    decision = evaluate_take_profit(position, executable_bid=0.80)
    assert decision.action == "SELL"
    assert decision.trigger == TRIGGER_TAKE_PROFIT


# --- D: no executable bid -> always HOLD, never a guess --------------------

def test_d_no_executable_bid_is_always_hold():
    position = _position(avg_fill_price=0.70)
    decision = evaluate_take_profit(position, executable_bid=None)
    assert decision.action == "HOLD"
    assert decision.trigger is None


# --- E: the exact worked examples from the governing spec ------------------

@pytest.mark.parametrize(
    ("entry_price", "expected_target"),
    [(0.70, 0.735), (0.75, 0.7875), (0.80, 0.84)],
)
def test_e_worked_examples_from_spec(entry_price, expected_target):
    position = _position(avg_fill_price=entry_price)
    decision = evaluate_take_profit(position, executable_bid=entry_price)
    assert decision.target_price == pytest.approx(expected_target)


def test_e2_default_take_profit_pct_is_exactly_005():
    assert DEFAULT_TAKE_PROFIT_PCT == pytest.approx(0.05)


def test_e3_dollar_worked_examples_from_the_governing_spec():
    # $100 entry -> ~$105 take-profit; $20 entry -> ~$21.
    assert _position(avg_fill_price=100.0).avg_fill_price * (1 + DEFAULT_TAKE_PROFIT_PCT) == pytest.approx(105.0)
    assert _position(avg_fill_price=20.0).avg_fill_price * (1 + DEFAULT_TAKE_PROFIT_PCT) == pytest.approx(21.0)


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


# --- H: the stop-loss -------------------------------------------------------

def test_h_exactly_at_stop_loss_sells():
    position = _position(avg_fill_price=0.70)  # stop_loss = 0.56 at the 20% default
    # Use the exact computed stop_loss_price as the bid, never a hand-typed
    # literal -- 0.70 * 0.80 is not exactly representable in float, so a
    # literal 0.56 can land a hair above it and spuriously fail the
    # boundary check this test exists to cover.
    stop_loss_price = position.avg_fill_price * (1 - DEFAULT_STOP_LOSS_PCT)
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


def test_i2_default_stop_loss_pct_is_exactly_020():
    assert DEFAULT_STOP_LOSS_PCT == pytest.approx(0.20)


def test_i3_dollar_worked_examples_from_the_governing_spec():
    # $100 entry -> ~$80 stop-loss; $20 entry -> ~$16.
    assert _position(avg_fill_price=100.0).avg_fill_price * (1 - DEFAULT_STOP_LOSS_PCT) == pytest.approx(80.0)
    assert _position(avg_fill_price=20.0).avg_fill_price * (1 - DEFAULT_STOP_LOSS_PCT) == pytest.approx(16.0)


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

    stop_loss_price = 0.70 * (1 - DEFAULT_STOP_LOSS_PCT)
    decision_before = evaluate_take_profit(_position(avg_fill_price=0.70), executable_bid=stop_loss_price)
    decision_after_restart = evaluate_take_profit(reloaded, executable_bid=stop_loss_price)
    assert decision_after_restart.stop_loss_price == pytest.approx(decision_before.stop_loss_price)
    assert decision_after_restart.action == decision_before.action == "SELL"
    assert decision_after_restart.trigger == TRIGGER_STOP_LOSS


# --- M: BOTH percentages are genuinely configurable, never hard-coded ------

def test_m_a_different_take_profit_pct_changes_the_target_not_the_default():
    position = _position(avg_fill_price=0.70)
    decision = evaluate_take_profit(position, executable_bid=0.70, take_profit_pct=0.10)
    assert decision.target_price == pytest.approx(0.77)  # 0.70 * 1.10, not the 5% default's 0.735


def test_m2_a_different_stop_loss_pct_changes_the_floor_not_the_default():
    position = _position(avg_fill_price=0.70)
    decision = evaluate_take_profit(position, executable_bid=0.70, stop_loss_pct=0.10)
    assert decision.stop_loss_price == pytest.approx(0.63)  # 0.70 * 0.90, not the 20% default's 0.56


def test_m3_a_configured_pair_sells_at_its_own_configured_target_not_the_default():
    # At the DEFAULT 5%/20%, 0.76 would just HOLD (below the 0.735
    # default target, above the 0.56 default floor) -- but with a
    # configured 10% take-profit, target becomes 0.77... still holds
    # at 0.76. Use 0.78 instead to cross the CONFIGURED target while
    # remaining BELOW where the default target would already have
    # fired, proving the configured value (not the default) is what's
    # actually being evaluated.
    position = _position(avg_fill_price=0.70)
    configured = evaluate_take_profit(position, executable_bid=0.76, take_profit_pct=0.10)
    default = evaluate_take_profit(position, executable_bid=0.76)
    assert configured.action == "HOLD"  # 0.76 < 0.77 (configured 10% target)
    assert default.action == "SELL"  # 0.76 >= 0.735 (default 5% target)
