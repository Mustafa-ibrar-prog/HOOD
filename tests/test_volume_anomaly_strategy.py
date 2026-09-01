"""Phase 8, Part 27: tests for VolumeAnomalyLongStrategy — volume-feature
calculation reuse, signal generation, holding-period exit, no-lookahead,
next-bar execution (via the real backtest engine), and reproducibility.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.backtesting import (
    BacktestConfig,
    BacktestRiskAdapter,
    FixedDollarSizer,
    FixedPercentSlippage,
    FixedPercentSpreadModel,
    NextBarExecutionModel,
    PerShareCommission,
)
from src.data.bar import Bar
from src.research import run_research_backtest
from src.research.volume_anomaly_strategy import VolumeAnomalyLongStrategy
from src.risk.manager import RiskManager
from src.risk.models import RiskLimits
from datetime import time as dtime

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _bars(symbol: str, volumes: list[int], *, price_start: float = 100.0) -> list[Bar]:
    out = []
    price = price_start
    for i, v in enumerate(volumes):
        out.append(Bar(timestamp=T0 + timedelta(days=i), symbol=symbol, timeframe="day", open=price, high=price + 1, low=price - 1, close=price, volume=v))
        price += 0.1  # gentle drift, avoids degenerate zero-return bars
    return out


def _risk_adapter() -> BacktestRiskAdapter:
    limits = RiskLimits(max_trades_per_day=10, max_daily_loss_usd=1_000_000.0, max_position_size_usd=20_000.0, cooldown_minutes_after_exit=0, stale_data_max_seconds=10**9, max_spread_pct=1.0, min_option_volume=0, min_option_open_interest=0, max_extended_move_pct=100.0, entry_cutoff_time=dtime(23, 59))
    return BacktestRiskAdapter(RiskManager(limits))


def _models():
    return dict(execution_model=NextBarExecutionModel(price_field="open", delay_bars=1), slippage_model=FixedPercentSlippage(0.001), cost_model=PerShareCommission(0.005), spread_model=FixedPercentSpreadModel(0.001), position_sizer=FixedDollarSizer(2000.0), risk_adapter=_risk_adapter())


def test_feature_engine_uses_the_exact_relative_volume_feature():
    strategy = VolumeAnomalyLongStrategy(strategy_id="T", baseline_lookback=10, anomaly_threshold=2.0, holding_period_bars=5, universe=["AAPL"])
    engine = strategy.feature_engine()
    manifest = engine.manifest()
    assert len(manifest) == 1
    assert manifest[0]["name"] == "relative_volume_10"
    assert manifest[0]["params"] == {"window": 10}


def test_no_signal_below_lookback_warmup():
    strategy = VolumeAnomalyLongStrategy(strategy_id="T", baseline_lookback=10, anomaly_threshold=2.0, holding_period_bars=5, universe=["AAPL"])
    bars = _bars("AAPL", [1000] * 5 + [5000])  # spike, but not enough history yet
    features = strategy.feature_engine().compute(bars)
    row = {name: features.columns[name][-1] for name in features.feature_names}
    signal = strategy.generate_signal(bars, row)
    assert signal is None  # relative_volume_10 is None before 10 bars of history exist


def test_signal_fires_on_a_genuine_volume_spike():
    strategy = VolumeAnomalyLongStrategy(strategy_id="T", baseline_lookback=10, anomaly_threshold=2.0, holding_period_bars=5, universe=["AAPL"])
    volumes = [1000] * 15 + [5000]  # a clean 5x spike after 15 bars of stable baseline
    bars = _bars("AAPL", volumes)
    features = strategy.feature_engine().compute(bars)
    row = {name: features.columns[name][-1] for name in features.feature_names}
    signal = strategy.generate_signal(bars, row)
    assert signal is not None
    assert signal.direction == "LONG"
    assert 0.0 <= signal.signal_strength <= 1.0


def test_no_signal_when_volume_is_ordinary():
    strategy = VolumeAnomalyLongStrategy(strategy_id="T", baseline_lookback=10, anomaly_threshold=2.0, holding_period_bars=5, universe=["AAPL"])
    bars = _bars("AAPL", [1000] * 20)  # flat volume, never a spike
    features = strategy.feature_engine().compute(bars)
    row = {name: features.columns[name][-1] for name in features.feature_names}
    signal = strategy.generate_signal(bars, row)
    assert signal is None


def test_holding_period_exit_fires_exactly_on_schedule():
    """Drives generate_signal bar-by-bar directly (bypassing the full
    engine) to verify the exit timer counts EXACTLY holding_period_bars,
    no early exit, no late exit."""
    strategy = VolumeAnomalyLongStrategy(strategy_id="T", baseline_lookback=5, anomaly_threshold=2.0, holding_period_bars=3, universe=["AAPL"])
    volumes = [1000] * 6 + [5000] + [1000] * 10  # spike at index 6, then flat
    bars = _bars("AAPL", volumes)
    directions = []
    for i in range(1, len(bars) + 1):
        history = bars[:i]
        features = strategy.feature_engine().compute(history)
        row = {name: features.columns[name][-1] for name in features.feature_names}
        signal = strategy.generate_signal(history, row)
        directions.append(signal.direction if signal else None)
    entry_index = directions.index("LONG")
    exit_index = directions.index("FLAT", entry_index + 1)
    assert exit_index - entry_index == 3  # exactly holding_period_bars later


def test_does_not_reenter_while_already_holding():
    strategy = VolumeAnomalyLongStrategy(strategy_id="T", baseline_lookback=5, anomaly_threshold=2.0, holding_period_bars=5, universe=["AAPL"])
    volumes = [1000] * 6 + [5000, 6000, 7000] + [1000] * 10  # THREE consecutive spikes right after entry
    bars = _bars("AAPL", volumes)
    directions = []
    for i in range(1, len(bars) + 1):
        history = bars[:i]
        features = strategy.feature_engine().compute(history)
        row = {name: features.columns[name][-1] for name in features.feature_names}
        signal = strategy.generate_signal(history, row)
        directions.append(signal.direction if signal else None)
    assert directions.count("LONG") == 1  # only the FIRST spike opened a position; the other two were ignored while held


def test_generate_signal_never_sees_future_bars():
    """Truncating the series vs. extending it with future bars must
    produce identical decisions for everything on or before the
    truncation point — same causal proof pattern as Phase 6."""
    strategy_short = VolumeAnomalyLongStrategy(strategy_id="T", baseline_lookback=10, anomaly_threshold=2.0, holding_period_bars=5, universe=["AAPL"])
    strategy_long = VolumeAnomalyLongStrategy(strategy_id="T", baseline_lookback=10, anomaly_threshold=2.0, holding_period_bars=5, universe=["AAPL"])
    volumes = [1000] * 15 + [5000] + [1000] * 30
    full_bars = _bars("AAPL", volumes)

    def run(strategy, bars):
        out = []
        for i in range(1, len(bars) + 1):
            history = bars[:i]
            features = strategy.feature_engine().compute(history)
            row = {name: features.columns[name][-1] for name in features.feature_names}
            signal = strategy.generate_signal(history, row)
            out.append(signal.direction if signal else None)
        return out

    short_run = run(strategy_short, full_bars[:20])
    long_run = run(strategy_long, full_bars)
    assert short_run == long_run[:20]


def test_full_backtest_uses_next_bar_execution_and_produces_real_trades():
    strategy = VolumeAnomalyLongStrategy(strategy_id="T", baseline_lookback=10, anomaly_threshold=1.5, holding_period_bars=5, universe=["AAPL"])
    volumes = [1000] * 15 + [3000] + [1000] * 20 + [3500] + [1000] * 20
    bars = {"AAPL": _bars("AAPL", volumes)}
    config = BacktestConfig(symbols=("AAPL",), timeframe="day", start=bars["AAPL"][0].timestamp.date(), end=bars["AAPL"][-1].timestamp.date(), data_version="v1", feature_version="v1", initial_capital_usd=100_000.0)
    result = run_research_backtest(research_strategy=strategy, bars_by_symbol=bars, config=config, **_models())
    assert len(result.trades) >= 1
    for t in result.trades:
        holding_days = (t.exit_timestamp - t.entry_timestamp).days
        assert holding_days == 5  # exactly the preregistered holding period


def test_reproducibility_same_bars_same_trades():
    volumes = [1000] * 15 + [3000] + [1000] * 20 + [3500] + [1000] * 20
    bars = {"AAPL": _bars("AAPL", volumes)}
    config = BacktestConfig(symbols=("AAPL",), timeframe="day", start=bars["AAPL"][0].timestamp.date(), end=bars["AAPL"][-1].timestamp.date(), data_version="v1", feature_version="v1", initial_capital_usd=100_000.0)
    r1 = run_research_backtest(research_strategy=VolumeAnomalyLongStrategy(strategy_id="T", baseline_lookback=10, anomaly_threshold=1.5, holding_period_bars=5, universe=["AAPL"]), bars_by_symbol=bars, config=config, **_models())
    r2 = run_research_backtest(research_strategy=VolumeAnomalyLongStrategy(strategy_id="T", baseline_lookback=10, anomaly_threshold=1.5, holding_period_bars=5, universe=["AAPL"]), bars_by_symbol=bars, config=config, **_models())
    assert [(t.entry_timestamp, t.net_pnl) for t in r1.trades] == [(t.entry_timestamp, t.net_pnl) for t in r2.trades]


def test_invalid_parameters_rejected():
    import pytest

    with pytest.raises(ValueError):
        VolumeAnomalyLongStrategy(strategy_id="T", baseline_lookback=0, anomaly_threshold=2.0, holding_period_bars=5, universe=["AAPL"])
    with pytest.raises(ValueError):
        VolumeAnomalyLongStrategy(strategy_id="T", baseline_lookback=10, anomaly_threshold=2.0, holding_period_bars=0, universe=["AAPL"])
