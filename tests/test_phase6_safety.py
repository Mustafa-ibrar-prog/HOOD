"""Phase 6, section 22/23 safety and correctness tests:
  - no live orders are submitted anywhere in Phase 6's code
  - the holdout runner never calls parameter-sweep/walk-forward machinery
    (holdout data must not be used to select strategy parameters)
  - future data cannot enter the frozen strategy's signal
  - transaction costs/slippage are correctly subtracted from gross P&L
  - execution stress changes execution, never strategy logic
"""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from src.backtesting import (
    BacktestConfig,
    BacktestRiskAdapter,
    FixedPercentSlippage,
    FixedPercentSpreadModel,
    FixedQuantitySizer,
    NextBarExecutionModel,
    PerShareCommission,
)
from src.data.bar import Bar
from src.research import build_mr002_frozen_definition, build_strategy_from_frozen, run_research_backtest
from src.research.strategy import ResearchStrategy
from src.risk.manager import RiskManager
from src.risk.models import RiskLimits

REPO_ROOT = Path(__file__).resolve().parent.parent


def _risk_adapter() -> BacktestRiskAdapter:
    limits = RiskLimits(max_trades_per_day=10, max_daily_loss_usd=1_000_000.0, max_position_size_usd=20_000.0, cooldown_minutes_after_exit=0, stale_data_max_seconds=10**9, max_spread_pct=1.0, min_option_volume=0, min_option_open_interest=0, max_extended_move_pct=100.0, entry_cutoff_time=time(23, 59))
    return BacktestRiskAdapter(RiskManager(limits))


def _bars(symbol: str, n: int, *, start=datetime(2024, 1, 1, tzinfo=timezone.utc)) -> list[Bar]:
    import math

    return [
        Bar(timestamp=start + timedelta(days=i), symbol=symbol, timeframe="day", open=100 + 10 * math.sin(i / 6), high=112, low=88, close=100 + 10 * math.sin(i / 6), volume=1000)
        for i in range(n)
    ]


# --- no live orders anywhere in Phase 6 code ------------------------------------------------


PHASE6_MODULES = [
    REPO_ROOT / "src" / "research" / "frozen_strategy.py",
    REPO_ROOT / "src" / "research" / "holdout.py",
    REPO_ROOT / "src" / "research" / "pass_criteria.py",
    REPO_ROOT / "src" / "research" / "paper_trading_gate.py",
    REPO_ROOT / "src" / "research" / "trade_distribution.py",
]
PHASE6_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase6_*.py"))

FORBIDDEN_IMPORT_PREFIXES = ("src.execution", "src.orchestrator")


def test_no_phase6_module_imports_the_live_execution_or_orchestrator_path():
    for path in PHASE6_MODULES + PHASE6_SCRIPTS:
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in FORBIDDEN_IMPORT_PREFIXES:
                    assert not node.module.startswith(prefix), f"{path} imports {node.module} (forbidden: {prefix})"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in FORBIDDEN_IMPORT_PREFIXES:
                        assert not alias.name.startswith(prefix), f"{path} imports {alias.name} (forbidden: {prefix})"


def test_no_phase6_module_calls_a_live_order_placement_function():
    """Static text scan for the live order-placement call names used
    elsewhere in this codebase (src.execution's gateway) — none of them
    should appear anywhere in Phase 6's source."""
    forbidden_calls = ("place_equity_order", "place_option_order", "place_crypto_order", "submit_order", "cancel_equity_order", "cancel_option_order")
    for path in PHASE6_MODULES + PHASE6_SCRIPTS:
        source = path.read_text()
        for call in forbidden_calls:
            assert call not in source, f"{path} references {call!r} — Phase 6 must never place or cancel a live/paper order"


# --- holdout data must never be used to select strategy parameters -------------------------


def test_the_holdout_runner_never_calls_parameter_sweep_or_walk_forward_machinery():
    """scripts/phase6_step5_run_holdout.py is the only script that touches
    holdout-period bars for evaluation — it must never call
    run_parameter_sweep or run_walk_forward, which would mean the holdout
    (or a subset of it) was used to pick a parameter."""
    holdout_runner = REPO_ROOT / "scripts" / "phase6_step5_run_holdout.py"
    source = holdout_runner.read_text()
    assert "run_parameter_sweep" not in source
    assert "run_walk_forward(" not in source


def test_the_freeze_and_holdout_split_scripts_also_avoid_parameter_selection():
    for name in ("phase6_step1_freeze_mr002.py", "phase6_step2_determine_holdout.py", "phase6_step3_define_pass_criteria.py"):
        source = (REPO_ROOT / "scripts" / name).read_text()
        assert "run_parameter_sweep" not in source
        assert "run_walk_forward(" not in source


# --- future data cannot enter the frozen strategy's signal ---------------------------------


def test_frozen_mr002_signal_is_unaffected_by_bars_appended_after_the_decision_point():
    """Truncating the series at bar N vs. extending it with 50 additional
    FUTURE bars must produce identical trades for everything entered on or
    before bar N — proof the frozen strategy's signal generation is causal."""
    definition = build_mr002_frozen_definition(development_universe_name="TEST")
    strategy_short = build_strategy_from_frozen(definition, ["AAPL"])
    strategy_long = build_strategy_from_frozen(definition, ["AAPL"])

    full_bars = _bars("AAPL", 150)
    short_bars = {"AAPL": full_bars[:100]}
    long_bars = {"AAPL": full_bars}  # same first 100 bars, plus 50 MORE bars appended after

    config = BacktestConfig(symbols=("AAPL",), timeframe="day", start=full_bars[0].timestamp.date(), end=full_bars[-1].timestamp.date(), data_version="v1", feature_version="v1", initial_capital_usd=100_000.0)
    models = dict(
        execution_model=NextBarExecutionModel(price_field="open", delay_bars=1), slippage_model=FixedPercentSlippage(0.001),
        cost_model=PerShareCommission(0.005), spread_model=FixedPercentSpreadModel(0.001), position_sizer=FixedQuantitySizer(20), risk_adapter=_risk_adapter(),
    )

    short_result = run_research_backtest(research_strategy=strategy_short, bars_by_symbol=short_bars, config=config, **models)
    long_result = run_research_backtest(research_strategy=strategy_long, bars_by_symbol=long_bars, config=config, **models)

    short_entries = [(t.symbol, t.entry_timestamp, t.entry_price) for t in short_result.trades]
    long_entries_in_short_window = [(t.symbol, t.entry_timestamp, t.entry_price) for t in long_result.trades if t.entry_timestamp <= full_bars[99].timestamp]
    assert short_entries == long_entries_in_short_window


# --- transaction costs / slippage are correctly applied ------------------------------------


def test_net_pnl_equals_gross_pnl_minus_fees_on_real_trades():
    """This engine's convention (src/backtesting/engine.py's
    _record_closed_trade, a documented fix from Phase 3): slippage is
    already baked into gross_pnl via the slippage-adjusted fill price
    (entry_price/exit_price), so net_pnl = gross_pnl - fees, NOT
    gross_pnl - fees - slippage (that would double-count slippage). The
    `slippage` field on BacktestTrade is informational (how much slippage
    cost was), not a second deduction. This test locks in the correct
    invariant so a future change can't silently reintroduce double-counting."""
    definition = build_mr002_frozen_definition(development_universe_name="TEST")
    strategy = build_strategy_from_frozen(definition, ["AAPL"])
    bars = {"AAPL": _bars("AAPL", 150)}
    config = BacktestConfig(symbols=("AAPL",), timeframe="day", start=bars["AAPL"][0].timestamp.date(), end=bars["AAPL"][-1].timestamp.date(), data_version="v1", feature_version="v1", initial_capital_usd=100_000.0)
    models = dict(
        execution_model=NextBarExecutionModel(price_field="open", delay_bars=1), slippage_model=FixedPercentSlippage(0.001),
        cost_model=PerShareCommission(0.005), spread_model=FixedPercentSpreadModel(0.001), position_sizer=FixedQuantitySizer(20), risk_adapter=_risk_adapter(),
    )
    result = run_research_backtest(research_strategy=strategy, bars_by_symbol=bars, config=config, **models)
    assert len(result.trades) > 0, "test setup should produce at least one trade to check cost math on"
    for t in result.trades:
        assert abs(t.net_pnl - (t.gross_pnl - t.fees)) < 1e-6
        assert t.fees >= 0
        assert t.slippage >= 0


# --- execution stress changes execution, never strategy logic ------------------------------


def test_generate_signal_has_no_execution_related_parameter():
    """Structural guarantee: ResearchStrategy.generate_signal's signature
    only takes (history, features) — there is no way for an execution
    model, slippage assumption, or cost multiplier to reach the signal
    generation code path at all."""
    sig = inspect.signature(ResearchStrategy.generate_signal)
    param_names = set(sig.parameters) - {"self"}
    assert param_names == {"history", "features"}


def test_running_the_same_execution_model_twice_is_deterministic():
    """A weaker, but reliably TRUE, complement to the structural signature
    check below: the engine itself is deterministic given the same
    strategy + execution config — repeating a run never silently changes
    the result. (An earlier version of this test asserted that two
    DIFFERENT execution delays must produce the same trade COUNT; that
    turned out to be false in general — a longer fill delay can shift
    which signals actually convert into closed trades near the end of the
    dataset and interact with the risk manager's per-day trade cap, so a
    different trade count doesn't mean strategy logic changed. The
    structural guarantee that matters — execution config cannot reach
    signal generation at all — is verified directly below instead.)"""
    definition = build_mr002_frozen_definition(development_universe_name="TEST")
    bars = {"AAPL": _bars("AAPL", 150)}
    config = BacktestConfig(symbols=("AAPL",), timeframe="day", start=bars["AAPL"][0].timestamp.date(), end=bars["AAPL"][-1].timestamp.date(), data_version="v1", feature_version="v1", initial_capital_usd=100_000.0)
    common = dict(execution_model=NextBarExecutionModel(price_field="open", delay_bars=1), slippage_model=FixedPercentSlippage(0.001), cost_model=PerShareCommission(0.005), spread_model=FixedPercentSpreadModel(0.001), position_sizer=FixedQuantitySizer(20), risk_adapter=_risk_adapter())

    result_a = run_research_backtest(research_strategy=build_strategy_from_frozen(definition, ["AAPL"]), bars_by_symbol=bars, config=config, **common)
    result_b = run_research_backtest(research_strategy=build_strategy_from_frozen(definition, ["AAPL"]), bars_by_symbol=bars, config=config, **common)

    assert [(t.entry_timestamp, t.entry_price, t.net_pnl) for t in result_a.trades] == [(t.entry_timestamp, t.entry_price, t.net_pnl) for t in result_b.trades]
