"""Controlled parameter-sweep framework (Phase 4, sections 6-7).

Explicitly NOT a strategy optimizer: run_parameter_sweep() runs every
combination in a grid and returns the full performance SURFACE — every
result, not just the best one. summarize_parameter_stability() then
answers "does this work across a range of reasonable parameters, or only
at one lucky point" — a strategy that collapses immediately outside one
parameter combination is exactly what this is built to catch, not to
hide by reporting only the winner.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from src.backtesting.execution_models import ExecutionModel, SlippageModel, SpreadModel, TransactionCostModel
from src.backtesting.interfaces import BacktestConfig
from src.backtesting.metrics import PerformanceMetrics
from src.backtesting.risk_adapter import BacktestRiskAdapter
from src.backtesting.sizing import PositionSizer
from src.data.bar import Bar
from src.research.analysis import mean, stdev
from src.research.runner import run_research_backtest
from src.research.strategy import ResearchStrategy


@dataclass(frozen=True)
class SweepPoint:
    parameters: Mapping[str, Any]
    metrics: PerformanceMetrics


@dataclass(frozen=True)
class ParameterStabilityReport:
    metric_name: str
    values: tuple[float | None, ...]  # aligned with the sweep's own parameter-combination order
    mean_value: float | None
    stdev_value: float | None
    min_value: float | None
    max_value: float | None
    fraction_acceptable: float | None  # fraction of combos clearing `acceptable_threshold`
    is_broadly_acceptable: bool | None  # True if fraction_acceptable is high (not just one lucky point)


def run_parameter_sweep(
    *,
    strategy_factory: Callable[[Mapping[str, Any]], ResearchStrategy],
    param_grid: Mapping[str, Sequence[Any]],
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    config: BacktestConfig,
    execution_model: ExecutionModel,
    slippage_model: SlippageModel,
    cost_model: TransactionCostModel,
    spread_model: SpreadModel,
    position_sizer: PositionSizer,
    risk_adapter: BacktestRiskAdapter,
) -> list[SweepPoint]:
    if not param_grid:
        raise ValueError("param_grid must have at least one parameter")
    names = list(param_grid.keys())
    combos = list(itertools.product(*(param_grid[n] for n in names)))

    points: list[SweepPoint] = []
    for combo in combos:
        params = dict(zip(names, combo))
        strategy = strategy_factory(params)
        result = run_research_backtest(
            research_strategy=strategy, bars_by_symbol=bars_by_symbol, config=config,
            execution_model=execution_model, slippage_model=slippage_model, cost_model=cost_model,
            spread_model=spread_model, position_sizer=position_sizer, risk_adapter=risk_adapter,
        )
        points.append(SweepPoint(parameters=params, metrics=result.metrics))
    return points


def summarize_parameter_stability(
    points: Sequence[SweepPoint], *, metric_fn: Callable[[PerformanceMetrics], float | None] = lambda m: m.returns.sharpe_ratio,
    metric_name: str = "sharpe_ratio", acceptable_threshold: float = 0.0,
) -> ParameterStabilityReport:
    values = [metric_fn(p.metrics) for p in points]
    non_null = [v for v in values if v is not None]
    if not non_null:
        return ParameterStabilityReport(metric_name=metric_name, values=tuple(values), mean_value=None, stdev_value=None, min_value=None, max_value=None, fraction_acceptable=None, is_broadly_acceptable=None)
    fraction_acceptable = sum(1 for v in non_null if v > acceptable_threshold) / len(non_null)
    return ParameterStabilityReport(
        metric_name=metric_name, values=tuple(values), mean_value=mean(non_null), stdev_value=stdev(non_null),
        min_value=min(non_null), max_value=max(non_null), fraction_acceptable=fraction_acceptable,
        # "Broadly acceptable" is deliberately a high bar (75%+ of the grid
        # clears the threshold) — a strategy that only works at one combo
        # out of many should NOT read as stable.
        is_broadly_acceptable=fraction_acceptable >= 0.75,
    )
