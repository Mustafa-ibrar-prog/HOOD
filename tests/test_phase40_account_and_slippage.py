"""Phase 40, Part 3/11/12/13/14/16/17/18/19/23 -- account math, bid/ask-only
execution pricing, cost breakdown, the PAPER_EXPERIMENT trade journal, the
equity curve, and daily performance rollups."""

from __future__ import annotations

import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.paper_trading.account import (
    available_cash_for_new_position,
    compute_account_snapshot,
)
from src.paper_trading.daily_performance import compute_daily_performance
from src.paper_trading.equity_curve import (
    EquitySnapshotStore,
    build_equity_snapshot,
)
from src.paper_trading.journal import (
    PAPER_EXPERIMENT_LABEL,
    PaperExperimentTradeRecord,
    PaperExperimentTradeStore,
    deterministic_trade_id,
)
from src.paper_trading.slippage import (
    NO_EXECUTABLE_QUOTE,
    SlippageAssumptionTier,
    compute_cost_breakdown,
    entry_execution_price,
    exit_execution_price,
)
from src.position_manager.models import OpenPosition
from src.strategy.decision import TradeThesis

NOW = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)


def _open_position(*, option_id="opt-1", entry_price=2.00, quantity=1, symbol="AAPL"):
    return OpenPosition(
        symbol=symbol, option_id=option_id, option_description=f"{symbol} 2026-09-18 C 230",
        side="long_call", quantity=quantity, entry_price=entry_price, entry_time=NOW,
        thesis=TradeThesis(setup_name="momentum_breakout", direction="bullish", catalyst="test", invalidation="test"),
        profit_target_usd=200.0, stop_loss_usd=100.0, expiration=date(2026, 9, 18),
    )


def _trade(*, trade_id="t1", net_pnl_usd=None, exit_timestamp=None, symbol="AAPL", entry_fill=2.0, quantity=1, entry_timestamp=NOW):
    return PaperExperimentTradeRecord(
        label=PAPER_EXPERIMENT_LABEL, experiment_id="exp-1", trade_id=trade_id, strategy_id="MOMENTUM_BREAKOUT_EXISTING_V1",
        strategy_content_hash="abc123", entry_observation_cycle_id="cyc-1",
        exit_observation_cycle_id=("cyc-2" if exit_timestamp else None), entry_timestamp=entry_timestamp,
        exit_timestamp=exit_timestamp, symbol=symbol, option_id="opt-1", strike=230.0, expiration=date(2026, 9, 18),
        option_type="call", dte_at_entry=10, moneyness_at_entry=0.01, entry_bid=1.9, entry_ask=2.0, entry_fill=entry_fill,
        exit_bid=(2.5 if exit_timestamp else None), exit_ask=(2.6 if exit_timestamp else None),
        exit_fill=(2.5 if exit_timestamp else None), quantity=quantity, gross_pnl_usd=net_pnl_usd,
        spread_cost_usd=(1.0 if net_pnl_usd is not None else None), slippage_usd=(0.5 if net_pnl_usd is not None else None),
        fees_usd=(0.65 if net_pnl_usd is not None else None), net_pnl_usd=net_pnl_usd,
        return_pct=(net_pnl_usd / (entry_fill * quantity * 100) if net_pnl_usd is not None else None),
        mfe_pct=None, mae_pct=None, exit_reason=("PROFIT_TARGET" if exit_timestamp else None),
        slippage_tier=SlippageAssumptionTier.BASELINE.value,
    )


# --- Slippage / execution pricing -------------------------------------------------------------


def test_entry_fills_at_the_real_ask_never_a_midpoint():
    result = entry_execution_price(bid=1.90, ask=2.00, tier=SlippageAssumptionTier.BASELINE)
    assert result.base_executable_price == 2.00


def test_exit_fills_at_the_real_bid_never_a_midpoint():
    result = exit_execution_price(bid=2.40, ask=2.50, tier=SlippageAssumptionTier.BASELINE)
    assert result.base_executable_price == 2.40


def test_entry_with_no_ask_returns_no_executable_quote_never_a_fabricated_price():
    assert entry_execution_price(bid=1.90, ask=None, tier=SlippageAssumptionTier.BASELINE) == NO_EXECUTABLE_QUOTE


def test_exit_with_no_bid_returns_no_executable_quote_never_a_fabricated_price():
    assert exit_execution_price(bid=None, ask=2.50, tier=SlippageAssumptionTier.STRESSED) == NO_EXECUTABLE_QUOTE


def test_stressed_tier_assumes_more_slippage_and_spread_than_baseline():
    baseline = entry_execution_price(bid=1.90, ask=2.00, tier=SlippageAssumptionTier.BASELINE)
    stressed = entry_execution_price(bid=1.90, ask=2.00, tier=SlippageAssumptionTier.STRESSED)
    assert stressed.slippage_usd_per_share > baseline.slippage_usd_per_share


def test_cost_breakdown_net_is_gross_minus_slippage_minus_fees():
    entry = entry_execution_price(bid=1.90, ask=2.00, tier=SlippageAssumptionTier.BASELINE)
    exit_ = exit_execution_price(bid=2.40, ask=2.50, tier=SlippageAssumptionTier.BASELINE)
    breakdown = compute_cost_breakdown(entry=entry, exit=exit_, quantity=1)
    assert breakdown.gross_pnl_usd == pytest.approx((2.40 - 2.00) * 100, abs=0.01)
    assert breakdown.net_pnl_usd == pytest.approx(breakdown.gross_pnl_usd - breakdown.slippage_usd - breakdown.fees_usd, abs=0.01)


# --- Trade journal ------------------------------------------------------------------------------


def test_trade_record_must_be_labeled_paper_experiment_never_live_trade():
    with pytest.raises(ValueError):
        PaperExperimentTradeRecord(
            label="LIVE_TRADE", experiment_id="exp-1", trade_id="t1", strategy_id="X", strategy_content_hash="h",
            entry_observation_cycle_id="cyc-1", exit_observation_cycle_id=None, entry_timestamp=NOW, exit_timestamp=None,
            symbol="AAPL", option_id="opt-1", strike=230.0, expiration=date(2026, 9, 18), option_type="call",
            dte_at_entry=10, moneyness_at_entry=0.0, entry_bid=1.9, entry_ask=2.0, entry_fill=2.0, exit_bid=None,
            exit_ask=None, exit_fill=None, quantity=1, gross_pnl_usd=None, spread_cost_usd=None, slippage_usd=None,
            fees_usd=None, net_pnl_usd=None, return_pct=None, mfe_pct=None, mae_pct=None, exit_reason=None,
            slippage_tier=SlippageAssumptionTier.BASELINE.value,
        )


def test_deterministic_trade_id_is_reproducible_across_a_restart():
    id1 = deterministic_trade_id(experiment_id="exp-1", option_id="opt-1", entry_observation_cycle_id="cyc-1")
    id2 = deterministic_trade_id(experiment_id="exp-1", option_id="opt-1", entry_observation_cycle_id="cyc-1")
    assert id1 == id2
    assert len(id1) == 24


def test_deterministic_trade_id_differs_for_a_different_cycle():
    id1 = deterministic_trade_id(experiment_id="exp-1", option_id="opt-1", entry_observation_cycle_id="cyc-1")
    id2 = deterministic_trade_id(experiment_id="exp-1", option_id="opt-1", entry_observation_cycle_id="cyc-2")
    assert id1 != id2


def test_trade_store_round_trips_through_dict():
    record = _trade()
    restored = PaperExperimentTradeRecord.from_dict(record.to_dict())
    assert restored == record


def test_trade_store_a_later_append_with_the_same_trade_id_updates_not_duplicates():
    with tempfile.TemporaryDirectory() as d:
        store = PaperExperimentTradeStore(Path(d) / "trades.jsonl")
        entry_only = _trade(trade_id="t1")
        store.append(entry_only)
        closed = _trade(trade_id="t1", net_pnl_usd=42.0, exit_timestamp=NOW + timedelta(hours=1))
        store.append(closed)
        all_rows = store.load_all()
        assert len(all_rows) == 1
        assert all_rows[0].net_pnl_usd == 42.0


def test_trade_store_survives_a_restart_fresh_instance_same_path():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "trades.jsonl"
        PaperExperimentTradeStore(path).append(_trade(trade_id="t1"))
        fresh = PaperExperimentTradeStore(path)
        assert fresh.get("t1") is not None


# --- Account snapshot -----------------------------------------------------------------------------


def test_starting_snapshot_with_no_trades_or_positions_equals_starting_capital():
    snapshot = compute_account_snapshot(as_of=NOW, starting_cash_usd=1000.0, closed_trades=[], open_positions=[], current_bid_by_option_id={})
    assert snapshot.cash_usd == 1000.0
    assert snapshot.equity_usd == 1000.0
    assert snapshot.total_return_pct == 0.0


def test_realized_pnl_from_closed_trades_flows_into_cash():
    closed = [_trade(trade_id="t1", net_pnl_usd=50.0, exit_timestamp=NOW)]
    snapshot = compute_account_snapshot(as_of=NOW, starting_cash_usd=1000.0, closed_trades=closed, open_positions=[], current_bid_by_option_id={})
    assert snapshot.cash_usd == 1050.0
    assert snapshot.realized_pnl_usd == 50.0


def test_open_position_commits_cash_and_contributes_unrealized_pnl():
    pos = _open_position(option_id="opt-1", entry_price=2.00, quantity=1)
    snapshot = compute_account_snapshot(
        as_of=NOW, starting_cash_usd=1000.0, closed_trades=[], open_positions=[pos],
        current_bid_by_option_id={"opt-1": 2.50},
    )
    # 200 committed to the position, then marked up to 250 executable value
    assert snapshot.cash_usd == 800.0
    assert snapshot.open_position_market_value_usd == 250.0
    assert snapshot.equity_usd == 1050.0
    assert snapshot.unrealized_pnl_usd == 50.0


def test_missing_current_quote_values_the_position_at_zero_never_guessed():
    pos = _open_position(option_id="opt-missing", entry_price=2.00, quantity=1)
    snapshot = compute_account_snapshot(as_of=NOW, starting_cash_usd=1000.0, closed_trades=[], open_positions=[pos], current_bid_by_option_id={})
    assert "opt-missing" in snapshot.positions_missing_a_current_quote
    assert snapshot.open_position_market_value_usd == 0.0


def test_cash_is_never_reported_as_negative_available_for_new_trades():
    snapshot = compute_account_snapshot(as_of=NOW, starting_cash_usd=100.0, closed_trades=[_trade(trade_id="t1", net_pnl_usd=-500.0, exit_timestamp=NOW)], open_positions=[], current_bid_by_option_id={})
    assert available_cash_for_new_position(snapshot) >= 0.0


def test_drawdown_is_zero_at_a_new_peak():
    snapshot = compute_account_snapshot(as_of=NOW, starting_cash_usd=1000.0, closed_trades=[_trade(trade_id="t1", net_pnl_usd=100.0, exit_timestamp=NOW)], open_positions=[], current_bid_by_option_id={}, historical_peak_equity_usd=1000.0)
    assert snapshot.current_drawdown_pct == 0.0
    assert snapshot.peak_equity_usd == 1100.0


def test_drawdown_reflects_a_decline_from_a_higher_historical_peak():
    snapshot = compute_account_snapshot(as_of=NOW, starting_cash_usd=1000.0, closed_trades=[_trade(trade_id="t1", net_pnl_usd=-100.0, exit_timestamp=NOW)], open_positions=[], current_bid_by_option_id={}, historical_peak_equity_usd=1200.0)
    assert snapshot.current_drawdown_pct == pytest.approx((1200.0 - 900.0) / 1200.0)


# --- Equity curve ---------------------------------------------------------------------------------


def test_equity_curve_dedupes_by_observation_cycle_id_restart_safe():
    with tempfile.TemporaryDirectory() as d:
        store = EquitySnapshotStore(Path(d) / "equity.jsonl")
        snapshot = compute_account_snapshot(as_of=NOW, starting_cash_usd=1000.0, closed_trades=[], open_positions=[], current_bid_by_option_id={})
        record = build_equity_snapshot(experiment_id="exp-1", observation_cycle_id="cyc-1", snapshot=snapshot, first_snapshot_equity_today=None)
        assert store.append(record) is True
        assert store.append(record) is False  # same cycle id -- restart-safe no-op
        assert len(store.load_all()) == 1


def test_equity_curve_survives_a_restart_dedup_state_reloaded():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "equity.jsonl"
        snapshot = compute_account_snapshot(as_of=NOW, starting_cash_usd=1000.0, closed_trades=[], open_positions=[], current_bid_by_option_id={})
        record = build_equity_snapshot(experiment_id="exp-1", observation_cycle_id="cyc-1", snapshot=snapshot, first_snapshot_equity_today=None)
        EquitySnapshotStore(path).append(record)
        fresh = EquitySnapshotStore(path)
        assert fresh.append(record) is False


def test_daily_pnl_is_none_for_the_days_own_first_snapshot():
    snapshot = compute_account_snapshot(as_of=NOW, starting_cash_usd=1000.0, closed_trades=[], open_positions=[], current_bid_by_option_id={})
    record = build_equity_snapshot(experiment_id="exp-1", observation_cycle_id="cyc-1", snapshot=snapshot, first_snapshot_equity_today=None)
    assert record.daily_pnl_usd is None


def test_daily_pnl_reflects_change_since_the_first_snapshot_of_the_day():
    snapshot = compute_account_snapshot(as_of=NOW, starting_cash_usd=1000.0, closed_trades=[_trade(trade_id="t1", net_pnl_usd=20.0, exit_timestamp=NOW)], open_positions=[], current_bid_by_option_id={})
    record = build_equity_snapshot(experiment_id="exp-1", observation_cycle_id="cyc-2", snapshot=snapshot, first_snapshot_equity_today=1000.0)
    assert record.daily_pnl_usd == pytest.approx(20.0)


# --- Daily performance -----------------------------------------------------------------------------


def test_zero_trades_on_a_day_is_a_valid_report_not_an_error():
    snapshot = compute_account_snapshot(as_of=NOW, starting_cash_usd=1000.0, closed_trades=[], open_positions=[], current_bid_by_option_id={})
    record = build_equity_snapshot(experiment_id="exp-1", observation_cycle_id="cyc-1", snapshot=snapshot, first_snapshot_equity_today=None)
    daily = compute_daily_performance([record], [])
    assert len(daily) == 1
    assert daily[0].trades_opened == 0
    assert daily[0].trades_closed == 0


def test_daily_performance_counts_wins_and_losses_closed_that_day():
    snapshot = compute_account_snapshot(as_of=NOW, starting_cash_usd=1000.0, closed_trades=[], open_positions=[], current_bid_by_option_id={})
    record = build_equity_snapshot(experiment_id="exp-1", observation_cycle_id="cyc-1", snapshot=snapshot, first_snapshot_equity_today=None)
    trades = [
        _trade(trade_id="win", net_pnl_usd=50.0, exit_timestamp=NOW),
        _trade(trade_id="loss", net_pnl_usd=-20.0, exit_timestamp=NOW),
    ]
    daily = compute_daily_performance([record], trades)
    assert daily[0].wins == 1
    assert daily[0].losses == 1
    assert daily[0].trades_closed == 2


def test_intraday_drawdown_is_none_with_fewer_than_two_snapshots():
    snapshot = compute_account_snapshot(as_of=NOW, starting_cash_usd=1000.0, closed_trades=[], open_positions=[], current_bid_by_option_id={})
    record = build_equity_snapshot(experiment_id="exp-1", observation_cycle_id="cyc-1", snapshot=snapshot, first_snapshot_equity_today=None)
    daily = compute_daily_performance([record], [])
    assert daily[0].max_intraday_drawdown_pct is None
