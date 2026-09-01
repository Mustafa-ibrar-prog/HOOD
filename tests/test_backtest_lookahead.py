"""AGGRESSIVE look-ahead and data-leakage tests for the full backtesting
engine (Phase 3, sections 18-19) — these intentionally try to break the
no-future-data guarantee, not just confirm the happy path."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.backtesting.engine import BacktestEngine
from src.backtesting.events import FillEvent, OrderEvent, SignalEvent
from src.backtesting.execution_models import FixedPercentSpreadModel, NextBarExecutionModel, ZeroCostModel, ZeroSlippage
from src.backtesting.interfaces import BacktestConfig
from src.backtesting.risk_adapter import BacktestRiskAdapter
from src.backtesting.sizing import FixedQuantitySizer
from src.backtesting.strategy import BacktestStrategy, Signal
from src.data.bar import Bar
from src.features.engine import FeatureEngine
from src.features.momentum import MovingAverage
from src.risk.manager import RiskManager
from src.risk.models import RiskLimits
from datetime import date, time

UTC = timezone.utc
CUTOFF = 40
TOTAL = 70


def _bars(closes: list[float], *, symbol="AAPL") -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol=symbol, timeframe="day", open=c, high=c + 0.5, low=c - 0.5, close=c, volume=1000 + i)
        for i, c in enumerate(closes)
    ]


def _base_closes() -> list[float]:
    return [100.0 + (0.6 if i % 3 else -1.1) for i in range(TOTAL)]


def _mutated_closes() -> list[float]:
    base = _base_closes()
    return base[: CUTOFF + 1] + [10_000_000.0 + i for i in range(TOTAL - CUTOFF - 1)]


def _permissive_risk_adapter() -> BacktestRiskAdapter:
    limits = RiskLimits(
        max_trades_per_day=1000, max_daily_loss_usd=10**9, max_position_size_usd=10**9,
        cooldown_minutes_after_exit=0, stale_data_max_seconds=10**9, max_spread_pct=1.0,
        min_option_volume=0, min_option_open_interest=0, max_extended_move_pct=100.0,
        entry_cutoff_time=time(23, 59),
    )
    return BacktestRiskAdapter(RiskManager(limits))


class _MACrossoverStrategy(BacktestStrategy):
    name = "leak-test-ma-crossover"

    def on_bar(self, history, features):
        fast, slow = features.get("sma_5"), features.get("sma_20")
        if fast is None or slow is None:
            return None
        return Signal(direction="LONG" if fast > slow else "FLAT")


class _RecordingStrategy(BacktestStrategy):
    """Records exactly the (history length, features dict) it was given at
    every bar, for direct comparison against an independent recomputation."""

    name = "recording-strategy"

    def __init__(self):
        self.seen: list[tuple[int, dict]] = []

    def on_bar(self, history, features):
        self.seen.append((len(history), dict(features)))
        return None


def _run(closes: list[float], strategy) -> "BacktestEngine":
    bars = _bars(closes)
    engine = BacktestEngine(
        config=BacktestConfig(symbols=("AAPL",), timeframe="day", start=date(2024, 1, 1), end=date(2025, 1, 1), data_version="dv", feature_version="fv", initial_capital_usd=1_000_000.0),
        bars_by_symbol={"AAPL": bars},
        strategy=strategy,
        feature_engine=FeatureEngine([MovingAverage(5), MovingAverage(20)]),
        execution_model=NextBarExecutionModel(price_field="open", delay_bars=1),
        slippage_model=ZeroSlippage(),
        cost_model=ZeroCostModel(),
        spread_model=FixedPercentSpreadModel(0.0),
        position_sizer=FixedQuantitySizer(10),
        risk_adapter=_permissive_risk_adapter(),
    )
    return engine


# --- 1 & 2: mutate future prices/volume dramatically; earlier signals unchanged --------------


def test_mutating_future_prices_does_not_change_earlier_signals():
    base_result = _run(_base_closes(), _MACrossoverStrategy()).run()
    mutated_result = _run(_mutated_closes(), _MACrossoverStrategy()).run()

    base_signals = [e for e in base_result.event_log if isinstance(e, SignalEvent) and e.timestamp <= _bars(_base_closes())[CUTOFF].timestamp]
    mutated_signals = [e for e in mutated_result.event_log if isinstance(e, SignalEvent) and e.timestamp <= _bars(_base_closes())[CUTOFF].timestamp]

    assert base_signals == mutated_signals
    assert len(base_signals) > 0  # sanity: the strategy actually produced signals to compare


def test_mutating_future_volume_does_not_change_earlier_features():
    """Same closes, but volume after the cutoff is wildly different — a
    volume-sensitive feature (relative volume) must not react before the
    cutoff."""
    from src.features.volume import RelativeVolume

    start = datetime(2024, 1, 1, tzinfo=UTC)
    closes = _base_closes()

    def build_bars(volumes: list[int]) -> list[Bar]:
        return [
            Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=c, high=c + 0.5, low=c - 0.5, close=c, volume=v)
            for i, (c, v) in enumerate(zip(closes, volumes))
        ]

    base_volumes = [1000 + (i * 7) % 200 for i in range(TOTAL)]
    mutated_volumes = base_volumes[: CUTOFF + 1] + [999_999_999] * (TOTAL - CUTOFF - 1)

    engine = FeatureEngine([RelativeVolume(10)])
    base_values = engine.compute(build_bars(base_volumes)).columns["relative_volume_10"]
    mutated_values = engine.compute(build_bars(mutated_volumes)).columns["relative_volume_10"]
    assert base_values[: CUTOFF + 1] == mutated_values[: CUTOFF + 1]


# --- 3: mutated future candles; earlier trades unchanged -------------------------------------


def test_mutating_future_candles_does_not_change_earlier_trades():
    base_result = _run(_base_closes(), _MACrossoverStrategy()).run()
    mutated_result = _run(_mutated_closes(), _MACrossoverStrategy()).run()
    cutoff_ts = _bars(_base_closes())[CUTOFF].timestamp

    def summarize(trades):
        return [
            (t.entry_timestamp, t.entry_price, t.exit_timestamp, t.exit_price, t.net_pnl)
            for t in trades
            if t.exit_timestamp <= cutoff_ts
        ]

    base_summary = summarize(base_result.trades)
    mutated_summary = summarize(mutated_result.trades)
    assert base_summary == mutated_summary
    assert len(base_summary) > 0


# --- 4: an order at T cannot execute using T+1 information unless the execution model allows it ---


def test_order_generated_at_bar_t_fills_using_bar_t_plus_delay_data_only():
    bars = _bars([100.0, 100.0, 100.0, 200.0, 300.0])  # a dramatic jump at index 3

    class _LongOnFirstBar(BacktestStrategy):
        name = "long-once"

        def __init__(self):
            self._done = False

        def on_bar(self, history, features):
            if not self._done:
                self._done = True
                return Signal(direction="LONG")
            return None

    engine = BacktestEngine(
        config=BacktestConfig(symbols=("AAPL",), timeframe="day", start=date(2024, 1, 1), end=date(2025, 1, 1), data_version="dv", feature_version="fv", initial_capital_usd=1_000_000.0),
        bars_by_symbol={"AAPL": bars},
        strategy=_LongOnFirstBar(),
        feature_engine=FeatureEngine([MovingAverage(1)]),
        execution_model=NextBarExecutionModel(price_field="open", delay_bars=1),
        slippage_model=ZeroSlippage(), cost_model=ZeroCostModel(), spread_model=FixedPercentSpreadModel(0.0),
        position_sizer=FixedQuantitySizer(1), risk_adapter=_permissive_risk_adapter(),
    )
    result = engine.run()
    fills = [e for e in result.event_log if isinstance(e, FillEvent) and e.status == "filled" and e.side == "buy"]
    assert len(fills) == 1
    # Signal generated from bar 0 (close=100.0). It must fill at bar 1's
    # open (100.0), NOT bar 0's own price and NOT any later bar's price
    # (e.g. the 200.0/300.0 jump at index 3).
    assert fills[0].timestamp == bars[1].timestamp
    assert fills[0].requested_price == pytest.approx(bars[1].open)
    assert fills[0].requested_price not in (bars[3].open, bars[4].open)

    orders = [e for e in result.event_log if isinstance(e, OrderEvent)]
    assert orders[0].generated_at_timestamp == bars[0].timestamp
    assert orders[0].timestamp == bars[1].timestamp  # fill-eligible time, strictly later


# --- 5: future targets are never accessible to a strategy during simulation ------------------


def test_backtesting_engine_never_imports_the_research_targets_module():
    """Structural guarantee: src.research.targets (the one deliberately
    forward-looking function in the codebase, see its own module
    docstring) must never be reachable from the backtesting engine's
    strategy-facing code path."""
    backtesting_dir = Path(__file__).resolve().parent.parent / "src" / "backtesting"
    for path in backtesting_dir.glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "research" not in node.module, f"{path.name} imports from {node.module} — future-target leakage risk"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "research" not in alias.name, f"{path.name} imports {alias.name} — future-target leakage risk"


def test_strategy_features_dict_never_contains_a_target_prefixed_key():
    strategy = _RecordingStrategy()
    _run(_base_closes(), strategy).run()
    assert strategy.seen  # sanity
    for _history_len, features in strategy.seen:
        assert not any(name.startswith("target_") for name in features)


# --- 6: rolling calculations (as actually used by the engine) use only historical observations ---


def test_windowed_feature_computation_matches_full_history_computation():
    """The engine slices history to a bounded recent window before calling
    FeatureEngine (a performance optimization — see engine.py's module
    docstring) — this proves that optimization produces byte-identical
    results to computing over the full, unbounded history at every bar."""
    closes = _base_closes()
    bars = _bars(closes)
    strategy = _RecordingStrategy()
    _run(closes, strategy).run()

    reference_engine = FeatureEngine([MovingAverage(5), MovingAverage(20)])
    for i, (history_len, features) in enumerate(strategy.seen):
        assert history_len == i + 1
        full_history_frame = reference_engine.compute(bars[: i + 1])
        expected = {name: full_history_frame.columns[name][-1] for name in full_history_frame.feature_names}
        assert features == expected, f"mismatch at bar index {i}"
