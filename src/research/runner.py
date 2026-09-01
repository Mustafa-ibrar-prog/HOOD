"""A small, reused helper that turns one ResearchStrategy into one
BacktestResult by running it through Phase 3's real BacktestEngine — every
module in this phase that needs "run a backtest" (parameter sweeps,
walk-forward, robustness, cost sensitivity, baselines) goes through this
single function rather than each re-wiring BacktestEngine construction.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from src.backtesting.engine import BacktestEngine, BacktestResult
from src.backtesting.execution_models import ExecutionModel, SlippageModel, SpreadModel, TransactionCostModel
from src.backtesting.interfaces import BacktestConfig
from src.backtesting.journal import BacktestTradeJournal
from src.backtesting.risk_adapter import BacktestRiskAdapter
from src.backtesting.sizing import PositionSizer
from src.data.bar import Bar
from src.research.strategy import ResearchStrategy, ResearchStrategyBacktestAdapter


def run_research_backtest(
    *,
    research_strategy: ResearchStrategy,
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    config: BacktestConfig,
    execution_model: ExecutionModel,
    slippage_model: SlippageModel,
    cost_model: TransactionCostModel,
    spread_model: SpreadModel,
    position_sizer: PositionSizer,
    risk_adapter: BacktestRiskAdapter,
    trade_journal: BacktestTradeJournal | None = None,
) -> BacktestResult:
    adapter = ResearchStrategyBacktestAdapter(research_strategy)
    engine = BacktestEngine(
        config=config,
        bars_by_symbol=bars_by_symbol,
        strategy=adapter,
        feature_engine=research_strategy.feature_engine(),
        execution_model=execution_model,
        slippage_model=slippage_model,
        cost_model=cost_model,
        spread_model=spread_model,
        position_sizer=position_sizer,
        risk_adapter=risk_adapter,
        trade_journal=trade_journal,
    )
    return engine.run()


def filter_bars_by_date(bars_by_symbol: Mapping[str, Sequence[Bar]], *, start, end) -> dict[str, list[Bar]]:
    """Slices each symbol's bar series to [start, end] (inclusive, by
    date) — the shared building block every window-based module (splits,
    walk-forward, robustness date-shifting) uses to carve out a period
    WITHOUT ever needing to know how the bars were originally fetched."""
    return {symbol: [b for b in bars if start <= b.timestamp.date() <= end] for symbol, bars in bars_by_symbol.items()}
