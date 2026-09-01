"""The event-driven backtesting engine (Phase 3).

Consumes Phase 2's normalized Bar/FeatureEngine directly. Genuinely reuses
src.risk.manager.RiskManager (via BacktestRiskAdapter) unmodified. Defines
its own BacktestStrategy/BacktestTradeJournal — see strategy.py and
journal.py's module docstrings for why Phase 2/pre-existing options-shaped
interfaces don't fit an equity/generic event-driven replay and were not
force-fit.

NEVER touches live or paper execution — see engine.py's module docstring
for the explicit architectural boundary.
"""

from __future__ import annotations

from src.backtesting.engine import BacktestEngine, BacktestResult
from src.backtesting.events import (
    EndOfPeriodEvent,
    EventQueue,
    FillEvent,
    LookAheadViolationError,
    MarketEvent,
    OrderEvent,
    PortfolioUpdateEvent,
    SignalEvent,
)
from src.backtesting.execution_models import (
    BasisPointSlippage,
    CompositeCostModel,
    FixedPercentSlippage,
    FixedPercentSpreadModel,
    NextBarExecutionModel,
    PerShareCommission,
    PercentOfNotionalCommission,
    PerSymbolSlippage,
    RealBidAskSpreadModel,
    SellOnlyFee,
    SizeAwareSlippage,
    SpreadQuote,
    VolatilityAdjustedSlippage,
    ZeroCostModel,
    ZeroSlippage,
    robinhood_equity_cost_model,
)
from src.backtesting.interfaces import BacktestConfig, HistoricalBarSource, StoreBackedBarSource
from src.backtesting.journal import BacktestTrade, BacktestTradeJournal
from src.backtesting.metrics import PerformanceMetrics, compute_benchmark_comparison, compute_performance_metrics
from src.backtesting.portfolio import EquityPoint, Portfolio, PortfolioError, Position
from src.backtesting.risk_adapter import BacktestRiskAdapter, RiskReview
from src.backtesting.sizing import (
    FixedDollarSizer,
    FixedFractionalRiskSizer,
    FixedQuantitySizer,
    PercentOfPortfolioSizer,
    PositionSizer,
    VolatilityBasedSizer,
)
from src.backtesting.strategy import BacktestStrategy, Signal

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "MarketEvent",
    "SignalEvent",
    "OrderEvent",
    "FillEvent",
    "PortfolioUpdateEvent",
    "EndOfPeriodEvent",
    "EventQueue",
    "LookAheadViolationError",
    "NextBarExecutionModel",
    "ZeroSlippage",
    "FixedPercentSlippage",
    "BasisPointSlippage",
    "VolatilityAdjustedSlippage",
    "PerSymbolSlippage",
    "SizeAwareSlippage",
    "ZeroCostModel",
    "PerShareCommission",
    "PercentOfNotionalCommission",
    "CompositeCostModel",
    "SellOnlyFee",
    "robinhood_equity_cost_model",
    "SpreadQuote",
    "FixedPercentSpreadModel",
    "RealBidAskSpreadModel",
    "BacktestConfig",
    "HistoricalBarSource",
    "StoreBackedBarSource",
    "BacktestTrade",
    "BacktestTradeJournal",
    "PerformanceMetrics",
    "compute_performance_metrics",
    "compute_benchmark_comparison",
    "Position",
    "Portfolio",
    "PortfolioError",
    "EquityPoint",
    "BacktestRiskAdapter",
    "RiskReview",
    "PositionSizer",
    "FixedQuantitySizer",
    "FixedDollarSizer",
    "PercentOfPortfolioSizer",
    "FixedFractionalRiskSizer",
    "VolatilityBasedSizer",
    "BacktestStrategy",
    "Signal",
]
