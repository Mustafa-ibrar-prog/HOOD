"""Focused tests for trade_learning.py (TASK 2) -- self-learning from
this bot's own completed trades as a SECONDARY, bounded adjustment to
entry_confidence.py's PRIMARY base confidence.

Pure-function / store-level tests only; engine.py's wiring (learning
applied inside run_cycle()) is covered by the "existing entry tests
still pass" regression suite (test_polymarket_btc_entry_signal.py) and
by test_polymarket_engine.py, never duplicated here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.polymarket.positions import OpenPosition
from src.polymarket.trade_learning import (
    OUTCOME_API_RECONCILIATION_EVENT,
    OUTCOME_EXECUTION_LOSS,
    OUTCOME_NORMAL_WIN,
    OUTCOME_STALE_ORDER_EVENT,
    OUTCOME_STRATEGY_LOSS,
    CompletedTrade,
    CompletedTradeStore,
    CompletedTradeStoreError,
    apply_historical_adjustment,
    build_setup_key,
    classify_outcome,
    compute_historical_adjustment,
    compute_setup_stats,
    record_completed_trade,
)

_T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _trade(**overrides) -> CompletedTrade:
    defaults = dict(
        strategy_id="COINBASE_MOMENTUM", condition_id="cond-1", outcome="YES",
        entry_timestamp=_T0, exit_timestamp=_T0 + timedelta(minutes=5),
        size_usd=5.0, entry_fill_price=0.50, exit_price=0.60, exit_reason="DYNAMIC_EXIT",
        fees_usd=0.0, realized_pnl_usd=1.0, win=True, outcome_classification=OUTCOME_NORMAL_WIN,
        btc_direction="bullish", momentum_state="STRENGTHENING", fired_signal_count=2,
        seconds_remaining_at_entry=600.0,
    )
    defaults.update(overrides)
    return CompletedTrade(**defaults)


def _position(**overrides) -> OpenPosition:
    defaults = dict(
        condition_id="cond-1", token_id="tok-1", outcome="YES", requested_size_usd=5.0,
        filled_shares=10.0, avg_fill_price=0.50, order_id="order-1", client_order_id="client-1",
        status="filled", opened_at=_T0, close_time=_T0 + timedelta(minutes=15),
    )
    defaults.update(overrides)
    return OpenPosition(**defaults)


# --- A: a completed trade persists and survives a fresh store instance -----

def test_a_completed_trade_persists_and_survives_restart(tmp_path):
    path = tmp_path / "completed_trades.json"
    store = CompletedTradeStore(path)
    store.append(_trade())

    reopened = CompletedTradeStore(path)  # a fresh instance -- "survives restart"
    trades = reopened.load()
    assert len(trades) == 1
    assert trades[0].condition_id == "cond-1"
    assert trades[0].realized_pnl_usd == pytest.approx(1.0)


def test_a2_appending_does_not_clobber_earlier_runs(tmp_path):
    path = tmp_path / "completed_trades.json"
    store = CompletedTradeStore(path)
    store.append(_trade(condition_id="cond-1"))
    store.append(_trade(condition_id="cond-2"))
    assert [t.condition_id for t in store.load()] == ["cond-1", "cond-2"]


# --- B: setup statistics -- sample count, wins, losses, win rate, avg,
# expectancy, total P&L ------------------------------------------------

def test_b_setup_stats_compute_sample_count_wins_losses_win_rate_expectancy():
    key = build_setup_key(
        btc_direction="bullish", momentum_state="STRENGTHENING", fired_signal_count=2,
        entry_fill_price=0.50, seconds_remaining_at_entry=600.0,
    )
    trades = [
        _trade(realized_pnl_usd=2.0, win=True, outcome_classification=OUTCOME_NORMAL_WIN),
        _trade(realized_pnl_usd=3.0, win=True, outcome_classification=OUTCOME_NORMAL_WIN),
        _trade(realized_pnl_usd=-1.0, win=False, outcome_classification=OUTCOME_STRATEGY_LOSS),
    ]
    stats = compute_setup_stats(trades, key)
    assert stats.sample_count == 3
    assert stats.wins == 2
    assert stats.losses == 1
    assert stats.win_rate == pytest.approx(2 / 3)
    assert stats.avg_win_usd == pytest.approx(2.5)
    assert stats.avg_loss_usd == pytest.approx(-1.0)
    assert stats.total_pnl_usd == pytest.approx(4.0)
    assert stats.expectancy_usd == pytest.approx((2 / 3) * 2.5 + (1 / 3) * -1.0)


def test_b2_non_matching_setup_is_excluded():
    key = build_setup_key(
        btc_direction="bullish", momentum_state="STRENGTHENING", fired_signal_count=2,
        entry_fill_price=0.50, seconds_remaining_at_entry=600.0,
    )
    trades = [_trade(btc_direction="bearish")]  # different setup entirely
    stats = compute_setup_stats(trades, key)
    assert stats.sample_count == 0
    assert stats.win_rate is None


# --- C: non-strategy events (execution/reconciliation/stale) are
# EXCLUDED from win/loss statistics -- "execution failures don't
# become strategy losses" ------------------------------------------

def test_c_non_strategy_outcomes_excluded_from_stats_not_counted_as_losses():
    key = build_setup_key(
        btc_direction="bullish", momentum_state="STRENGTHENING", fired_signal_count=2,
        entry_fill_price=0.50, seconds_remaining_at_entry=600.0,
    )
    trades = [
        _trade(realized_pnl_usd=2.0, win=True, outcome_classification=OUTCOME_NORMAL_WIN),
        _trade(realized_pnl_usd=-5.0, win=False, outcome_classification=OUTCOME_STALE_ORDER_EVENT),
        _trade(realized_pnl_usd=-3.0, win=False, outcome_classification=OUTCOME_EXECUTION_LOSS),
        _trade(realized_pnl_usd=-4.0, win=False, outcome_classification=OUTCOME_API_RECONCILIATION_EVENT),
    ]
    stats = compute_setup_stats(trades, key)
    # Only the one NORMAL_WIN counts toward the strategy's own record --
    # the three non-strategy losses must never drag down win_rate/expectancy.
    assert stats.sample_count == 1
    assert stats.wins == 1
    assert stats.losses == 0
    assert stats.win_rate == pytest.approx(1.0)
    assert stats.excluded_non_strategy_count == 3


def test_c2_classify_outcome_prioritizes_non_strategy_flags_over_pnl_sign():
    # A big realized loss caused by a stale/delayed entry must NEVER be
    # classified as an ordinary STRATEGY_LOSS.
    assert classify_outcome(realized_pnl_usd=-50.0, stale_entry=True) == OUTCOME_STALE_ORDER_EVENT
    assert classify_outcome(realized_pnl_usd=-50.0, execution_failure=True) == OUTCOME_EXECUTION_LOSS
    assert classify_outcome(realized_pnl_usd=-50.0, reconciliation_event=True) == OUTCOME_API_RECONCILIATION_EVENT
    assert classify_outcome(realized_pnl_usd=-1.0) == OUTCOME_STRATEGY_LOSS
    assert classify_outcome(realized_pnl_usd=1.0) == OUTCOME_NORMAL_WIN


# --- D: minimum sample / anti-overfitting -----------------------------

def test_d_small_sample_causes_little_to_no_adjustment():
    key = build_setup_key(
        btc_direction="bullish", momentum_state="STRENGTHENING", fired_signal_count=2,
        entry_fill_price=0.50, seconds_remaining_at_entry=600.0,
    )
    # Two wins, zero losses (100% win rate) but only n=2 against a
    # min_sample_size of 20 -- shrinkage must keep this small.
    trades = [_trade(realized_pnl_usd=5.0) for _ in range(2)]
    stats = compute_setup_stats(trades, key)
    result = compute_historical_adjustment(stats, min_sample_size=20, min_adjustment=-10.0, max_adjustment=10.0)
    assert abs(result.adjustment) < 2.0  # nowhere near the +-10 cap despite a perfect win rate


def test_d2_zero_sample_yields_exactly_zero_adjustment():
    key = build_setup_key(
        btc_direction="bullish", momentum_state="STRENGTHENING", fired_signal_count=2,
        entry_fill_price=0.50, seconds_remaining_at_entry=600.0,
    )
    stats = compute_setup_stats([], key)
    result = compute_historical_adjustment(stats, min_sample_size=20, min_adjustment=-10.0, max_adjustment=10.0)
    assert result.adjustment == 0.0


# --- E: a profitable setup increases confidence, a poor one decreases --

def test_e_profitable_setup_at_full_sample_increases_confidence():
    key = build_setup_key(
        btc_direction="bullish", momentum_state="STRENGTHENING", fired_signal_count=2,
        entry_fill_price=0.50, seconds_remaining_at_entry=600.0,
    )
    trades = [_trade(realized_pnl_usd=2.0, win=True) for _ in range(18)] + [
        _trade(realized_pnl_usd=-1.0, win=False, outcome_classification=OUTCOME_STRATEGY_LOSS) for _ in range(2)
    ]
    stats = compute_setup_stats(trades, key)  # n=20, 90% win rate
    result = compute_historical_adjustment(stats, min_sample_size=20, min_adjustment=-10.0, max_adjustment=10.0)
    assert result.adjustment > 5.0
    final = apply_historical_adjustment(72, result.adjustment)
    assert final > 72


def test_e2_poor_setup_at_full_sample_decreases_confidence():
    key = build_setup_key(
        btc_direction="bullish", momentum_state="STRENGTHENING", fired_signal_count=2,
        entry_fill_price=0.50, seconds_remaining_at_entry=600.0,
    )
    trades = [_trade(realized_pnl_usd=-1.0, win=False, outcome_classification=OUTCOME_STRATEGY_LOSS) for _ in range(18)] + [
        _trade(realized_pnl_usd=2.0, win=True) for _ in range(2)
    ]
    stats = compute_setup_stats(trades, key)  # n=20, 10% win rate
    result = compute_historical_adjustment(stats, min_sample_size=20, min_adjustment=-10.0, max_adjustment=10.0)
    assert result.adjustment < -5.0
    final = apply_historical_adjustment(72, result.adjustment)
    assert final < 72


# --- F: the adjustment is ALWAYS capped at the configured bounds -----

def test_f_adjustment_never_exceeds_configured_bounds_even_at_huge_sample():
    key = build_setup_key(
        btc_direction="bullish", momentum_state="STRENGTHENING", fired_signal_count=2,
        entry_fill_price=0.50, seconds_remaining_at_entry=600.0,
    )
    trades = [_trade(realized_pnl_usd=100.0, win=True) for _ in range(500)]  # 100% win rate, huge n
    stats = compute_setup_stats(trades, key)
    result = compute_historical_adjustment(stats, min_sample_size=20, min_adjustment=-10.0, max_adjustment=10.0)
    assert result.adjustment == pytest.approx(10.0)

    all_losses = [_trade(realized_pnl_usd=-100.0, win=False, outcome_classification=OUTCOME_STRATEGY_LOSS) for _ in range(500)]
    stats_losses = compute_setup_stats(all_losses, key)
    result_losses = compute_historical_adjustment(stats_losses, min_sample_size=20, min_adjustment=-10.0, max_adjustment=10.0)
    assert result_losses.adjustment == pytest.approx(-10.0)


# --- G: historical data can NEVER create or reverse a direction -------

def test_g_historical_adjustment_cannot_create_a_trade_from_zero_confidence():
    # base_confidence == 0 means neutral/no-trade upstream -- even a
    # maximally positive adjustment must never turn this into a trade.
    assert apply_historical_adjustment(0, 10.0) == 0
    assert apply_historical_adjustment(0, -10.0) == 0


def test_g2_historical_adjustment_never_pushes_outside_0_100():
    assert apply_historical_adjustment(95, 10.0) == 100  # clamped, not 105
    assert apply_historical_adjustment(52, -10.0) == 42
    assert 0 <= apply_historical_adjustment(5, -10.0) <= 100


# --- H: a corrupted learning store fails SAFE (raises, never silently
# returns fabricated/partial data) --------------------------------

def test_h_corrupted_learning_store_raises_rather_than_fabricating(tmp_path):
    path = tmp_path / "completed_trades.json"
    path.write_text("{not valid json at all")
    store = CompletedTradeStore(path)
    with pytest.raises(CompletedTradeStoreError):
        store.load()


def test_h2_missing_file_is_simply_empty_not_an_error(tmp_path):
    store = CompletedTradeStore(tmp_path / "does_not_exist.json")
    assert store.load() == []


# --- I: record_completed_trade() -- the ONE place a closed position
# becomes a CompletedTrade, reading entry_context (TASK 2, 2A) -----

def test_i2_record_completed_trade_with_store(tmp_path):
    store = CompletedTradeStore(tmp_path / "completed_trades.json")
    position = _position(entry_context={
        "strategy_id": "COINBASE_MOMENTUM", "btc_direction": "bullish", "btc_edge_points": 2.0,
        "momentum_state": "STRENGTHENING", "fired_signal_count": 2, "base_confidence": 55,
        "confidence_bucket": "MINIMUM", "final_confidence": 55,
    })
    trade = record_completed_trade(
        store, position, exit_timestamp=_T0 + timedelta(minutes=10), exit_price=0.60,
        exit_reason="DYNAMIC_EXIT", fees_usd=0.05, realized_pnl_usd=1.0,
    )
    assert trade is not None
    assert trade.outcome_classification == OUTCOME_NORMAL_WIN
    assert trade.btc_direction == "bullish"
    assert trade.base_confidence == 55
    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0].condition_id == position.condition_id


def test_i3_record_completed_trade_is_a_noop_without_a_store():
    position = _position()
    result = record_completed_trade(
        None, position, exit_timestamp=_T0, exit_price=0.5, exit_reason="SETTLEMENT",
        fees_usd=0.0, realized_pnl_usd=1.0,
    )
    assert result is None


def test_i4_stale_entry_fill_classifies_as_stale_order_event_not_strategy_loss(tmp_path):
    store = CompletedTradeStore(tmp_path / "completed_trades.json")
    position = _position(entry_context={"stale_entry_fill": True})
    trade = record_completed_trade(
        store, position, exit_timestamp=_T0, exit_price=0.28, exit_reason="SETTLEMENT",
        fees_usd=0.0, realized_pnl_usd=-1.79,
    )
    assert trade.outcome_classification == OUTCOME_STALE_ORDER_EVENT
    assert trade.stale_entry is True
