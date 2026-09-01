"""Walk-forward research, robustness testing, and cost sensitivity (Phase
4, sections 14-16) — the three "does this survive being pushed around"
checks every candidate strategy goes through before any classification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Mapping, Sequence

from src.backtesting.execution_models import ExecutionModel, SlippageModel, SpreadModel, TransactionCostModel
from src.backtesting.interfaces import BacktestConfig
from src.backtesting.journal import BacktestTrade
from src.backtesting.metrics import PerformanceMetrics, compute_performance_metrics
from src.backtesting.risk_adapter import BacktestRiskAdapter
from src.backtesting.sizing import PositionSizer
from src.data.bar import Bar
from src.research.runner import filter_bars_by_date, run_research_backtest
from src.research.strategy import ResearchStrategy

# ==============================================================================
# WALK-FORWARD (section 14)
# ==============================================================================


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date

    def __post_init__(self) -> None:
        if not (self.train_start <= self.train_end < self.validation_start <= self.validation_end < self.test_start <= self.test_end):
            raise ValueError("walk-forward window periods must be chronological and non-overlapping")


def generate_walk_forward_windows(*, start: date, end: date, train_days: int, validation_days: int, test_days: int, step_days: int) -> list[WalkForwardWindow]:
    if min(train_days, validation_days, test_days, step_days) < 1:
        raise ValueError("all window lengths must be >= 1 day")
    windows: list[WalkForwardWindow] = []
    cursor = start
    while True:
        train_start = cursor
        train_end = train_start + timedelta(days=train_days - 1)
        validation_start = train_end + timedelta(days=1)
        validation_end = validation_start + timedelta(days=validation_days - 1)
        test_start = validation_end + timedelta(days=1)
        test_end = test_start + timedelta(days=test_days - 1)
        if test_end > end:
            break
        windows.append(WalkForwardWindow(train_start, train_end, validation_start, validation_end, test_start, test_end))
        cursor = cursor + timedelta(days=step_days)
    return windows


@dataclass(frozen=True)
class WalkForwardWindowResult:
    window: WalkForwardWindow
    selected_parameters: Mapping[str, Any]
    validation_score: float | None
    test_trades: tuple[BacktestTrade, ...]


@dataclass(frozen=True)
class WalkForwardReport:
    window_results: tuple[WalkForwardWindowResult, ...]
    aggregated_oos_trades: tuple[BacktestTrade, ...]
    aggregated_oos_metrics: PerformanceMetrics
    distinct_parameter_selections: int  # how many different param combos got picked across windows — a stability signal


def _trades_in_range(trades: Sequence[BacktestTrade], start: date, end: date) -> list[BacktestTrade]:
    return [t for t in trades if start <= t.entry_timestamp.date() <= end]


def run_walk_forward(
    *,
    strategy_factory: Callable[[Mapping[str, Any]], ResearchStrategy],
    param_grid: Mapping[str, Sequence[Any]],
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    windows: Sequence[WalkForwardWindow],
    config_template: BacktestConfig,
    execution_model: ExecutionModel,
    slippage_model: SlippageModel,
    cost_model: TransactionCostModel,
    spread_model: SpreadModel,
    position_sizer: PositionSizer,
    risk_adapter: BacktestRiskAdapter,
    selection_metric_fn: Callable[[PerformanceMetrics], float | None] = lambda m: m.trades.expectancy,
) -> WalkForwardReport:
    """For each window: sweep `param_grid` over [train_start, validation_end]
    (features need real lookback history, so parameter candidates are
    scored using only the trades whose ENTRY falls inside the validation
    sub-period — never using anything from the test period). The winning
    combo by `selection_metric_fn` (default: trade expectancy — robust to
    a filtered trade subset with no continuous equity curve of its own) is
    FROZEN, then re-run over [train_start, test_end] with the SAME frozen
    parameters; only trades entered inside the test sub-period count as
    out-of-sample. Rolls forward through every window, then aggregates all
    OOS trades together.
    """
    import itertools

    names = list(param_grid.keys())
    combos = [dict(zip(names, c)) for c in itertools.product(*(param_grid[n] for n in names))]

    window_results: list[WalkForwardWindowResult] = []
    all_oos_trades: list[BacktestTrade] = []

    for window in windows:
        dev_bars = filter_bars_by_date(bars_by_symbol, start=window.train_start, end=window.validation_end)

        best_params: Mapping[str, Any] | None = None
        best_score: float | None = None
        for params in combos:
            strategy = strategy_factory(params)
            result = run_research_backtest(
                research_strategy=strategy, bars_by_symbol=dev_bars, config=config_template,
                execution_model=execution_model, slippage_model=slippage_model, cost_model=cost_model,
                spread_model=spread_model, position_sizer=position_sizer, risk_adapter=risk_adapter,
            )
            validation_trades = _trades_in_range(result.trades, window.validation_start, window.validation_end)
            metrics = compute_performance_metrics(equity_curve=[], trades=validation_trades, starting_cash=config_template.initial_capital_usd)
            score = selection_metric_fn(metrics)
            if score is not None and (best_score is None or score > best_score):
                best_score, best_params = score, params

        if best_params is None:
            best_params = combos[0]  # no combo produced any validation trades — fall back rather than crash

        test_bars = filter_bars_by_date(bars_by_symbol, start=window.train_start, end=window.test_end)
        frozen_strategy = strategy_factory(best_params)
        test_result = run_research_backtest(
            research_strategy=frozen_strategy, bars_by_symbol=test_bars, config=config_template,
            execution_model=execution_model, slippage_model=slippage_model, cost_model=cost_model,
            spread_model=spread_model, position_sizer=position_sizer, risk_adapter=risk_adapter,
        )
        oos_trades = _trades_in_range(test_result.trades, window.test_start, window.test_end)
        all_oos_trades.extend(oos_trades)
        window_results.append(WalkForwardWindowResult(window=window, selected_parameters=best_params, validation_score=best_score, test_trades=tuple(oos_trades)))

    aggregated_metrics = compute_performance_metrics(equity_curve=[], trades=all_oos_trades, starting_cash=config_template.initial_capital_usd)
    distinct = len({tuple(sorted(r.selected_parameters.items())) for r in window_results})
    return WalkForwardReport(window_results=tuple(window_results), aggregated_oos_trades=tuple(all_oos_trades), aggregated_oos_metrics=aggregated_metrics, distinct_parameter_selections=distinct)


# ==============================================================================
# ROBUSTNESS (section 15)
# ==============================================================================


@dataclass(frozen=True)
class RobustnessCheck:
    dimension: str  # "parameter" | "date_range" | "symbol" | "cost" | "slippage"
    description: str
    metric_name: str
    base_value: float | None
    perturbed_value: float | None
    held: bool | None  # None if either value is unavailable to compare


@dataclass(frozen=True)
class RobustnessReport:
    checks: tuple[RobustnessCheck, ...]

    @property
    def fraction_held(self) -> float | None:
        evaluated = [c for c in self.checks if c.held is not None]
        if not evaluated:
            return None
        return sum(1 for c in evaluated if c.held) / len(evaluated)


def _score(result_trades: Sequence[BacktestTrade], starting_cash: float, metric_fn: Callable[[PerformanceMetrics], float | None]) -> float | None:
    return metric_fn(compute_performance_metrics(equity_curve=[], trades=list(result_trades), starting_cash=starting_cash))


def run_robustness_tests(
    *,
    strategy_factory: Callable[[Mapping[str, Any]], ResearchStrategy],
    base_parameters: Mapping[str, Any],
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    config: BacktestConfig,
    execution_model: ExecutionModel,
    slippage_model: SlippageModel,
    cost_model: TransactionCostModel,
    spread_model: SpreadModel,
    position_sizer: PositionSizer,
    risk_adapter: BacktestRiskAdapter,
    parameter_perturbations: Mapping[str, Sequence[Any]] | None = None,
    metric_fn: Callable[[PerformanceMetrics], float | None] = lambda m: m.trades.expectancy,
    held_threshold: float = 0.0,
) -> RobustnessReport:
    base_strategy = strategy_factory(base_parameters)
    base_result = run_research_backtest(
        research_strategy=base_strategy, bars_by_symbol=bars_by_symbol, config=config, execution_model=execution_model,
        slippage_model=slippage_model, cost_model=cost_model, spread_model=spread_model, position_sizer=position_sizer, risk_adapter=risk_adapter,
    )
    base_score = _score(base_result.trades, config.initial_capital_usd, metric_fn)

    checks: list[RobustnessCheck] = [RobustnessCheck("parameter", "base parameters", "metric", base_score, base_score, base_score is not None and base_score > held_threshold)]

    for param_name, values in (parameter_perturbations or {}).items():
        for value in values:
            if value == base_parameters.get(param_name):
                continue
            perturbed_params = dict(base_parameters)
            perturbed_params[param_name] = value
            strategy = strategy_factory(perturbed_params)
            result = run_research_backtest(
                research_strategy=strategy, bars_by_symbol=bars_by_symbol, config=config, execution_model=execution_model,
                slippage_model=slippage_model, cost_model=cost_model, spread_model=spread_model, position_sizer=position_sizer, risk_adapter=risk_adapter,
            )
            score = _score(result.trades, config.initial_capital_usd, metric_fn)
            checks.append(RobustnessCheck("parameter", f"{param_name}={value}", "metric", base_score, score, score is not None and score > held_threshold))

    return RobustnessReport(checks=tuple(checks))


# ==============================================================================
# COST SENSITIVITY (section 16)
# ==============================================================================


class _ScaledCostModel(TransactionCostModel):
    def __init__(self, base: TransactionCostModel, multiplier: float):
        self._base = base
        self._multiplier = multiplier

    def compute_fees(self, *, side: str, quantity: int, execution_price: float) -> float:
        return self._base.compute_fees(side=side, quantity=quantity, execution_price=execution_price) * self._multiplier


class _ScaledSlippageModel(SlippageModel):
    def __init__(self, base: SlippageModel, multiplier: float):
        self._base = base
        self._multiplier = multiplier

    def slippage_amount(self, **kwargs) -> float:
        return self._base.slippage_amount(**kwargs) * self._multiplier


@dataclass(frozen=True)
class CostSensitivityPoint:
    cost_multiplier: float
    slippage_multiplier: float
    trade_count: int
    net_pnl_total: float
    viable: bool  # net_pnl_total > 0 at this stress level


@dataclass(frozen=True)
class CostSensitivityReport:
    points: tuple[CostSensitivityPoint, ...]
    viable_at_base: bool
    viable_at_2x: bool | None
    viable_at_3x: bool | None


# ==============================================================================
# EXECUTION ROBUSTNESS (Phase 5, section 13)
# ==============================================================================


@dataclass(frozen=True)
class ExecutionRobustnessPoint:
    scenario: str  # e.g. "base (next-bar open, 1x slippage, 1x cost)", "extra 1-bar delay", "2x slippage", "2x cost"
    trade_count: int
    net_pnl_total: float
    viable: bool


@dataclass(frozen=True)
class ExecutionRobustnessReport:
    points: tuple[ExecutionRobustnessPoint, ...]

    @property
    def fraction_viable(self) -> float | None:
        if not self.points:
            return None
        return sum(1 for p in self.points if p.viable) / len(self.points)


def run_execution_robustness(
    *,
    research_strategy: ResearchStrategy,
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    config: BacktestConfig,
    base_execution_model: ExecutionModel,
    base_slippage_model: SlippageModel,
    base_cost_model: TransactionCostModel,
    spread_model: SpreadModel,
    position_sizer: PositionSizer,
    risk_adapter: BacktestRiskAdapter,
) -> ExecutionRobustnessReport:
    """Section 13's exact scenario list: BASE (next-bar open), an
    additional execution delay, higher slippage, and higher transaction
    costs — the strategy must not depend on unrealistically perfect
    execution to look good."""
    from src.backtesting.execution_models import NextBarExecutionModel

    scenarios: list[tuple[str, ExecutionModel, SlippageModel, TransactionCostModel]] = [
        ("base (next-bar open)", base_execution_model, base_slippage_model, base_cost_model),
        ("extra execution delay (+1 bar)", NextBarExecutionModel(price_field="open", delay_bars=base_execution_model.delay_bars() + 1), base_slippage_model, base_cost_model),
        ("higher slippage (2x)", base_execution_model, _ScaledSlippageModel(base_slippage_model, 2.0), base_cost_model),
        ("higher transaction costs (2x)", base_execution_model, base_slippage_model, _ScaledCostModel(base_cost_model, 2.0)),
    ]

    points = []
    for label, execution_model, slippage_model, cost_model in scenarios:
        result = run_research_backtest(
            research_strategy=research_strategy, bars_by_symbol=bars_by_symbol, config=config, execution_model=execution_model,
            slippage_model=slippage_model, cost_model=cost_model, spread_model=spread_model, position_sizer=position_sizer, risk_adapter=risk_adapter,
        )
        net_total = sum(t.net_pnl for t in result.trades)
        points.append(ExecutionRobustnessPoint(scenario=label, trade_count=len(result.trades), net_pnl_total=net_total, viable=net_total > 0))

    return ExecutionRobustnessReport(points=tuple(points))


def run_cost_sensitivity(
    *,
    research_strategy: ResearchStrategy,
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    config: BacktestConfig,
    execution_model: ExecutionModel,
    base_slippage_model: SlippageModel,
    base_cost_model: TransactionCostModel,
    spread_model: SpreadModel,
    position_sizer: PositionSizer,
    risk_adapter: BacktestRiskAdapter,
    multipliers: Sequence[float] = (1.0, 2.0, 3.0),
) -> CostSensitivityReport:
    points: list[CostSensitivityPoint] = []
    for m in multipliers:
        result = run_research_backtest(
            research_strategy=research_strategy, bars_by_symbol=bars_by_symbol, config=config, execution_model=execution_model,
            slippage_model=_ScaledSlippageModel(base_slippage_model, m), cost_model=_ScaledCostModel(base_cost_model, m),
            spread_model=spread_model, position_sizer=position_sizer, risk_adapter=risk_adapter,
        )
        net_total = sum(t.net_pnl for t in result.trades)
        points.append(CostSensitivityPoint(cost_multiplier=m, slippage_multiplier=m, trade_count=len(result.trades), net_pnl_total=net_total, viable=net_total > 0))

    by_mult = {p.cost_multiplier: p.viable for p in points}
    return CostSensitivityReport(
        points=tuple(points),
        viable_at_base=by_mult.get(1.0, points[0].viable if points else False),
        viable_at_2x=by_mult.get(2.0),
        viable_at_3x=by_mult.get(3.0),
    )
