"""Phase 11, Parts 16, 27: cost and execution stress testing FOR
CONTINUOUS-EXPOSURE STRATEGIES — measured from the EQUITY CURVE'S total
return, not from summed BacktestTrade.net_pnl.

WHY THIS EXISTS (found by inspecting an implausible result before
reporting it): src.research.validation's run_cost_sensitivity /
run_execution_robustness_extended (Phase 5/6, unmodified) measure
"viable" via `sum(t.net_pnl for t in trades)`. That is exactly right for
a strategy that opens and fully closes DISCRETE trades — but a
continuously-rebalanced exposure strategy (Phase 11's whole design) never
fully closes its position until the single, forced end-of-period close,
so BacktestEngine records exactly ONE BacktestTrade for the entire run,
whose gross_pnl is computed from only the FINAL average cost basis and
FINAL quantity — it silently DISCARDS the realized P&L of every earlier
partial buy/sell along the way. Running the frozen Phase 11 winner
through the unmodified helper produced a large apparent LOSS
(net_pnl_total ~ -$2,200) that contradicted the same run's own equity
curve (which had grown ~9-10% annualized) — the trade-level P&L
attribution, not the strategy, was wrong for this shape of strategy. This
module fixes the MEASUREMENT, not the strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from src.backtesting.execution_models import ExecutionModel, NextBarExecutionModel, SlippageModel, SpreadModel, TransactionCostModel
from src.backtesting.interfaces import BacktestConfig
from src.backtesting.risk_adapter import BacktestRiskAdapter
from src.backtesting.sizing import PositionSizer
from src.data.bar import Bar
from src.research.exposure_risk_adapter import ExposureRiskAdapter
from src.research.runner import run_research_backtest
from src.research.strategy import ResearchStrategy
from src.research.validation import _ScaledCostModel, _ScaledSlippageModel


@dataclass(frozen=True)
class ExposureStressPoint:
    label: str
    ending_equity: float
    total_return_pct: float
    viable: bool  # total_return_pct > 0


@dataclass(frozen=True)
class ExposureStressReport:
    points: tuple[ExposureStressPoint, ...]

    def render(self) -> str:
        return "\n".join(f"  {p.label}: ending_equity=${p.ending_equity:,.2f}  total_return={p.total_return_pct:+.2f}%  viable={p.viable}" for p in self.points)


def run_exposure_cost_stress(
    *, research_strategy: ResearchStrategy, bars_by_symbol: Mapping[str, Sequence[Bar]], config: BacktestConfig,
    execution_model: ExecutionModel, base_slippage_model: SlippageModel, base_cost_model: TransactionCostModel,
    spread_model: SpreadModel, position_sizer: PositionSizer, risk_adapter: BacktestRiskAdapter | ExposureRiskAdapter,
    multipliers: Sequence[float] = (1.0, 2.0, 3.0),
) -> ExposureStressReport:
    points = []
    for mult in multipliers:
        result = run_research_backtest(
            research_strategy=research_strategy, bars_by_symbol=bars_by_symbol, config=config, execution_model=execution_model,
            slippage_model=_ScaledSlippageModel(base_slippage_model, mult), cost_model=_ScaledCostModel(base_cost_model, mult),
            spread_model=spread_model, position_sizer=position_sizer, risk_adapter=risk_adapter,
        )
        total_return_pct = (result.ending_equity - config.initial_capital_usd) / config.initial_capital_usd * 100
        points.append(ExposureStressPoint(label=f"{mult:.0f}x", ending_equity=result.ending_equity, total_return_pct=total_return_pct, viable=total_return_pct > 0))
    return ExposureStressReport(points=tuple(points))


def run_exposure_execution_stress(
    *, research_strategy: ResearchStrategy, bars_by_symbol: Mapping[str, Sequence[Bar]], config: BacktestConfig,
    base_execution_model: ExecutionModel, base_slippage_model: SlippageModel, base_cost_model: TransactionCostModel,
    spread_model: SpreadModel, position_sizer: PositionSizer, risk_adapter: BacktestRiskAdapter | ExposureRiskAdapter,
) -> ExposureStressReport:
    scenarios: list[tuple[str, ExecutionModel, SlippageModel, TransactionCostModel]] = [
        ("BASE (next-bar open)", base_execution_model, base_slippage_model, base_cost_model),
        ("STRESS 1 (extra execution delay, +1 bar)", NextBarExecutionModel(price_field="open", delay_bars=base_execution_model.delay_bars() + 1), base_slippage_model, base_cost_model),
        ("STRESS 2 (higher slippage, 2x)", base_execution_model, _ScaledSlippageModel(base_slippage_model, 2.0), base_cost_model),
        ("STRESS 3 (combined: +1 bar delay AND 2x slippage)", NextBarExecutionModel(price_field="open", delay_bars=base_execution_model.delay_bars() + 1), _ScaledSlippageModel(base_slippage_model, 2.0), base_cost_model),
    ]
    points = []
    for label, execution_model, slippage_model, cost_model in scenarios:
        result = run_research_backtest(
            research_strategy=research_strategy, bars_by_symbol=bars_by_symbol, config=config, execution_model=execution_model,
            slippage_model=slippage_model, cost_model=cost_model, spread_model=spread_model, position_sizer=position_sizer, risk_adapter=risk_adapter,
        )
        total_return_pct = (result.ending_equity - config.initial_capital_usd) / config.initial_capital_usd * 100
        points.append(ExposureStressPoint(label=label, ending_equity=result.ending_equity, total_return_pct=total_return_pct, viable=total_return_pct > 0))
    return ExposureStressReport(points=tuple(points))
