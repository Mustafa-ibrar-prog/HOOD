"""Integration tests for BacktestEngine: event ordering, execution timing,
cash/position accounting, and the edge cases from Phase 3 section 24."""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone

import pytest

from src.backtesting.engine import BacktestEngine
from src.backtesting.events import FillEvent, MarketEvent, OrderEvent, SignalEvent
from src.backtesting.execution_models import FixedPercentSlippage, FixedPercentSpreadModel, NextBarExecutionModel, PerShareCommission, ZeroCostModel, ZeroSlippage
from src.backtesting.interfaces import BacktestConfig
from src.backtesting.risk_adapter import BacktestRiskAdapter
from src.backtesting.sizing import FixedQuantitySizer
from src.backtesting.strategy import BacktestStrategy, Signal
from src.data.bar import Bar
from src.features.engine import FeatureEngine
from src.features.momentum import MovingAverage
from src.risk.manager import RiskManager
from src.risk.models import RiskLimits

UTC = timezone.utc


def _bars(symbol: str, closes: list[float], *, start_day: int = 1, volume: int = 10_000) -> list[Bar]:
    start = datetime(2024, 1, start_day, 9, 30, tzinfo=UTC)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol=symbol, timeframe="day", open=c, high=c + 0.5, low=c - 0.5, close=c, volume=volume)
        for i, c in enumerate(closes)
    ]


def _permissive_risk_adapter(**overrides) -> BacktestRiskAdapter:
    defaults = dict(
        max_trades_per_day=1000, max_daily_loss_usd=1_000_000.0, max_position_size_usd=1_000_000.0,
        cooldown_minutes_after_exit=0, stale_data_max_seconds=10**9, max_spread_pct=1.0,
        min_option_volume=0, min_option_open_interest=0, max_extended_move_pct=100.0,
        entry_cutoff_time=time(23, 59),
    )
    defaults.update(overrides)
    return BacktestRiskAdapter(RiskManager(RiskLimits(**defaults)))


def _config(*, symbols=("AAPL",), initial_capital_usd=100_000.0, **overrides) -> BacktestConfig:
    defaults = dict(
        symbols=symbols, timeframe="day", start=date(2024, 1, 1), end=date(2024, 12, 31),
        data_version="dv", feature_version="fv", initial_capital_usd=initial_capital_usd,
    )
    defaults.update(overrides)
    return BacktestConfig(**defaults)


class _CrossoverAtIndexStrategy(BacktestStrategy):
    """A minimal, fully deterministic test strategy: go LONG on a
    specific bar index, FLAT on another — lets tests control exactly when
    trades happen without depending on real crossover math."""

    name = "test-index-strategy"
    version = "1.0"

    def __init__(self, long_at_index: int | None = None, flat_at_index: int | None = None):
        self._long_at = long_at_index
        self._flat_at = flat_at_index
        self._index = -1

    def on_bar(self, history, features):
        self._index += 1
        if self._index == self._long_at:
            return Signal(direction="LONG", reason="test long")
        if self._index == self._flat_at:
            return Signal(direction="FLAT", reason="test flat")
        return None


class _AlwaysErrorStrategy(BacktestStrategy):
    name = "broken-strategy"

    def on_bar(self, history, features):
        raise RuntimeError("strategy exploded")


def _no_op_feature_engine() -> FeatureEngine:
    return FeatureEngine([MovingAverage(2)])


def _build_engine(strategy, bars, *, sizer=None, risk_adapter=None, slippage=None, cost=None, spread=None, **engine_overrides):
    return BacktestEngine(
        config=_config(),
        bars_by_symbol={"AAPL": bars},
        strategy=strategy,
        feature_engine=_no_op_feature_engine(),
        execution_model=NextBarExecutionModel(price_field="open", delay_bars=1),
        slippage_model=slippage or ZeroSlippage(),
        cost_model=cost or ZeroCostModel(),
        spread_model=spread or FixedPercentSpreadModel(0.0),
        position_sizer=sizer or FixedQuantitySizer(10),
        risk_adapter=risk_adapter or _permissive_risk_adapter(),
        **engine_overrides,
    )


# --- basic scenarios -----------------------------------------------------------------------


def test_no_trades_when_strategy_never_signals():
    bars = _bars("AAPL", [100.0] * 10)
    strategy = _CrossoverAtIndexStrategy()  # never signals
    result = _build_engine(strategy, bars).run()
    assert result.trades == ()
    assert len(result.equity_curve) == 10
    assert result.ending_equity == pytest.approx(result.starting_cash)


def test_one_trade_full_round_trip():
    bars = _bars("AAPL", [100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
    strategy = _CrossoverAtIndexStrategy(long_at_index=1, flat_at_index=3)
    result = _build_engine(strategy, bars).run()
    assert len(result.trades) == 1
    trade = result.trades[0]
    # signal at bar index 1 (close 101) -> fills at bar index 2's open (102)
    assert trade.entry_price == pytest.approx(102.0)
    # signal at bar index 3 (close 103) -> fills at bar index 4's open (104)
    assert trade.exit_price == pytest.approx(104.0)
    assert trade.quantity == 10


def test_multiple_trades():
    bars = _bars("AAPL", [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0])
    strategy = _CrossoverAtIndexStrategy()
    strategy._long_at = 0  # patched after construction is awkward; use a custom multi-toggle strategy instead

    class _Toggle(BacktestStrategy):
        name = "toggle"

        def __init__(self):
            self._i = -1

        def on_bar(self, history, features):
            self._i += 1
            if self._i in (0, 4):
                return Signal(direction="LONG")
            if self._i in (2, 6):
                return Signal(direction="FLAT")
            return None

    result = _build_engine(_Toggle(), bars).run()
    assert len(result.trades) == 2


def test_same_symbol_consecutive_trades_reuse_state_correctly():
    bars = _bars("AAPL", [100.0] * 12)

    class _Toggle(BacktestStrategy):
        name = "toggle2"

        def __init__(self):
            self._i = -1

        def on_bar(self, history, features):
            self._i += 1
            if self._i % 3 == 0:
                return Signal(direction="LONG")
            if self._i % 3 == 1:
                return Signal(direction="FLAT")
            return None

    result = _build_engine(_Toggle(), bars).run()
    assert len(result.trades) >= 2
    for trade in result.trades:
        assert trade.entry_timestamp < trade.exit_timestamp


def test_zero_position_after_close_and_position_reopens_cleanly():
    bars = _bars("AAPL", [100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
    strategy = _CrossoverAtIndexStrategy(long_at_index=0, flat_at_index=2)
    result = _build_engine(strategy, bars).run()
    assert len(result.trades) == 1
    # position must be fully flat afterward — no dangling shares
    assert result.equity_curve[-1].open_position_count == 0


# --- cash / order rejection -----------------------------------------------------------------


def test_insufficient_cash_rejects_the_fill_not_the_whole_backtest():
    bars = _bars("AAPL", [100.0, 101.0, 102.0])
    strategy = _CrossoverAtIndexStrategy(long_at_index=0)
    # Sizer wants far more shares than the tiny starting capital can afford —
    # risk adapter's own position-size limit is generous, so this reaches the
    # portfolio's own cash check.
    engine = _build_engine(
        strategy, bars, sizer=FixedQuantitySizer(1_000_000),
        risk_adapter=_permissive_risk_adapter(max_position_size_usd=10**9),
    )
    engine._portfolio.cash = 50.0  # force a tiny cash balance directly
    engine._portfolio.starting_cash = 50.0
    result = engine.run()
    assert result.trades == ()
    rejected_fills = [e for e in result.event_log if isinstance(e, FillEvent) and e.status == "rejected"]
    assert rejected_fills


def test_risk_rejection_produces_no_order_and_a_rejected_fill_record():
    bars = _bars("AAPL", [100.0, 101.0, 102.0])
    strategy = _CrossoverAtIndexStrategy(long_at_index=0)
    strict_adapter = _permissive_risk_adapter(max_trades_per_day=0)
    result = _build_engine(strategy, bars, risk_adapter=strict_adapter).run()
    assert result.trades == ()
    rejected = [e for e in result.event_log if isinstance(e, FillEvent) and e.status == "rejected"]
    assert rejected
    orders = [e for e in result.event_log if isinstance(e, OrderEvent)]
    assert orders[0].risk_decision == "REJECTED"


def test_signal_at_the_very_end_of_data_cannot_execute_and_is_marked_rejected():
    bars = _bars("AAPL", [100.0, 101.0, 102.0])
    strategy = _CrossoverAtIndexStrategy(long_at_index=2)  # last bar — no future bar to fill against
    result = _build_engine(strategy, bars).run()
    assert result.trades == ()
    rejected = [e for e in result.event_log if isinstance(e, FillEvent) and e.status == "rejected"]
    assert any("end of dataset" in e.reason for e in rejected)


# --- slippage / fees --------------------------------------------------------------------------


def test_slippage_and_fees_reduce_net_pnl_versus_frictionless():
    bars = _bars("AAPL", [100.0, 101.0, 102.0, 103.0])
    strategy = _CrossoverAtIndexStrategy(long_at_index=0, flat_at_index=2)

    frictionless = _build_engine(strategy.__class__(long_at_index=0, flat_at_index=2), bars).run()
    with_costs = _build_engine(
        strategy, bars, slippage=FixedPercentSlippage(0.01), cost=PerShareCommission(0.05)
    ).run()
    assert with_costs.trades[0].net_pnl < frictionless.trades[0].net_pnl


def test_fees_larger_than_gross_profit_produce_a_losing_trade_not_a_crash():
    bars = _bars("AAPL", [100.0, 100.5, 101.0, 101.2])
    strategy = _CrossoverAtIndexStrategy(long_at_index=0, flat_at_index=2)
    result = _build_engine(strategy, bars, cost=PerShareCommission(0.0, minimum=10_000.0)).run()
    assert len(result.trades) == 1
    assert result.trades[0].net_pnl < 0


# --- strategy errors --------------------------------------------------------------------------


def test_strategy_exception_propagates_rather_than_being_swallowed():
    bars = _bars("AAPL", [100.0, 101.0, 102.0])
    engine = _build_engine(_AlwaysErrorStrategy(), bars)
    with pytest.raises(RuntimeError, match="strategy exploded"):
        engine.run()


# --- edge-case datasets -----------------------------------------------------------------------


def test_empty_dataset_returns_a_valid_empty_result():
    engine = _build_engine(_CrossoverAtIndexStrategy(), [])
    result = engine.run()
    assert result.trades == ()
    assert result.equity_curve == ()
    assert result.ending_equity == pytest.approx(result.starting_cash)


def test_one_row_dataset_is_safe_and_produces_no_signal():
    bars = _bars("AAPL", [100.0])
    strategy = _CrossoverAtIndexStrategy(long_at_index=0)
    result = _build_engine(strategy, bars).run()
    assert len(result.equity_curve) == 1
    # a LONG signal on the only bar has nowhere to fill (no future bar) —
    # gracefully rejected, not a crash.
    assert result.trades == ()


def test_extremely_large_price_movement_does_not_crash():
    bars = _bars("AAPL", [100.0, 1_000_000.0, 0.01, 500.0, 500.0])
    strategy = _CrossoverAtIndexStrategy(long_at_index=0, flat_at_index=2)
    result = _build_engine(strategy, bars).run()
    # The signal was sized/risk-approved against bar 0's $100 close, but
    # fills at bar 1's $1,000,000 open — a 10,000x jump the $100,000
    # starting capital genuinely cannot afford at 10 shares. The engine
    # must complete without raising and correctly REJECT the unaffordable
    # fill rather than crash or silently go cash-negative.
    assert len(result.trades) == 0
    rejected = [e for e in result.event_log if isinstance(e, FillEvent) and e.status == "rejected"]
    assert rejected
    assert "insufficient cash" in rejected[0].reason


def test_gap_in_timestamps_does_not_crash_the_engine():
    start = datetime(2024, 1, 1, tzinfo=UTC)
    bars = [
        Bar(timestamp=start, symbol="AAPL", timeframe="day", open=100, high=101, low=99, close=100, volume=100),
        Bar(timestamp=start + timedelta(days=30), symbol="AAPL", timeframe="day", open=101, high=102, low=100, close=101, volume=100),  # big gap
        Bar(timestamp=start + timedelta(days=31), symbol="AAPL", timeframe="day", open=102, high=103, low=101, close=102, volume=100),
    ]
    strategy = _CrossoverAtIndexStrategy(long_at_index=0)
    result = _build_engine(strategy, bars).run()
    assert len(result.trades) == 1  # fills fine at the next available bar despite the gap


# --- reproducibility -----------------------------------------------------------------------


def test_identical_inputs_produce_identical_results():
    bars = _bars("AAPL", [100.0 + math.sin(i / 3) * 5 for i in range(30)])

    def build():
        strategy = _CrossoverAtIndexStrategy(long_at_index=2, flat_at_index=10)
        return _build_engine(strategy, list(bars), slippage=FixedPercentSlippage(0.001), cost=PerShareCommission(0.01)).run()

    result_a = build()
    result_b = build()
    assert result_a.ending_equity == result_b.ending_equity
    assert [t.net_pnl for t in result_a.trades] == [t.net_pnl for t in result_b.trades]
    assert [t.entry_timestamp for t in result_a.trades] == [t.entry_timestamp for t in result_b.trades]
    assert len(result_a.event_log) == len(result_b.event_log)


# --- event ordering / auditability -----------------------------------------------------------


def test_event_log_is_strictly_chronological():
    bars = _bars("AAPL", [100.0, 101.0, 102.0, 103.0, 104.0])
    strategy = _CrossoverAtIndexStrategy(long_at_index=0, flat_at_index=2)
    result = _build_engine(strategy, bars).run()
    timestamps = [e.timestamp for e in result.event_log]
    assert timestamps == sorted(timestamps)


def test_order_event_records_full_audit_fields():
    bars = _bars("AAPL", [100.0, 101.0, 102.0])
    strategy = _CrossoverAtIndexStrategy(long_at_index=0)
    result = _build_engine(strategy, bars).run()
    orders = [e for e in result.event_log if isinstance(e, OrderEvent)]
    assert orders
    order = orders[0]
    assert order.symbol == "AAPL"
    assert order.side == "buy"
    assert order.risk_decision in ("APPROVED", "MODIFIED")
    assert order.strategy_name == strategy.name


def test_fill_event_records_full_audit_fields():
    bars = _bars("AAPL", [100.0, 101.0, 102.0])
    strategy = _CrossoverAtIndexStrategy(long_at_index=0)
    result = _build_engine(strategy, bars, slippage=FixedPercentSlippage(0.01), cost=PerShareCommission(0.05)).run()
    fills = [e for e in result.event_log if isinstance(e, FillEvent) and e.status == "filled"]
    assert fills
    fill = fills[0]
    assert fill.execution_price != fill.requested_price  # slippage applied
    assert fill.fees > 0
    assert fill.spread_source == "modeled_spread"
