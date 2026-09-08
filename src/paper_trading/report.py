"""Phase 40, Part 26-28 — final-report data aggregation.

Pure aggregation over the experiment's own persisted stores — never a
second source of truth, never a number computed a different way than
the equity curve / trade journal already computed it. Part 27's
presentation requirements (show starting/ending capital, net P&L,
return, max drawdown, trade count; never hide a losing period; never
annualize and imply predictiveness) are enforced by what this module
DOES NOT compute — there is no `annualized_return` field anywhere here.

Part 28: this module has no function, field, or code path that could
mark a strategy VALIDATED — it only ever reads the real, current
`src.production.registry` classification (read-only) to include in the
report for cross-reference, exactly as Part 2 requires ("Verify: live
authorization = OFF... Do NOT change this to VALIDATED_STRATEGY").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from src.paper_trading.account import PaperExperimentAccountSnapshot
from src.paper_trading.daily_performance import DailyPerformanceRecord, compute_daily_performance
from src.paper_trading.equity_curve import EquitySnapshotRecord
from src.paper_trading.experiment_config import ExperimentConfig
from src.paper_trading.journal import PaperExperimentTradeRecord

MINIMUM_SAMPLE_WARNING = (
    "Two weeks is a small sample. This report describes what happened during THIS "
    "specific experiment window and is not a prediction of future performance, "
    "annualized or otherwise. No annualized return is reported."
)


@dataclass(frozen=True)
class TradingStatsReport:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float | None
    average_win_usd: float | None
    average_loss_usd: float | None
    expectancy_usd: float | None  # win_rate * avg_win + (1 - win_rate) * avg_loss (avg_loss negative)
    profit_factor: float | None  # sum(wins) / abs(sum(losses)), None if no losses
    average_holding_minutes: float | None


@dataclass(frozen=True)
class ExecutionQualityReport:
    average_quoted_spread_usd: float | None
    average_slippage_usd: float | None
    total_fees_usd: float
    rejected_fills: int  # NO_EXECUTABLE_QUOTE occurrences (caller-tracked, not derivable from the trade store alone)
    missing_quotes: int
    execution_quality_failures: int  # rejected_fills + missing_quotes, for a single top-line figure


@dataclass(frozen=True)
class PortfolioReport:
    max_exposure_usd: float
    average_exposure_usd: float
    largest_position_usd: float
    max_concentration_symbol: str | None
    max_concentration_pct: float | None
    unique_contracts_traded: int


@dataclass(frozen=True)
class FinalExperimentReport:
    config: ExperimentConfig
    experiment_status: str
    calendar_days_elapsed: int
    market_days_observed: int
    starting_capital_usd: float
    ending_equity_usd: float | None
    net_pnl_usd: float | None
    total_return_pct: float | None
    max_drawdown_pct: float | None
    peak_equity_usd: float | None
    lowest_equity_usd: float | None
    trading: TradingStatsReport
    execution: ExecutionQualityReport
    portfolio: PortfolioReport
    daily_performance: tuple[DailyPerformanceRecord, ...]
    equity_curve: tuple[EquitySnapshotRecord, ...]  # the raw dataset "suitable for plotting" (Part 26)
    small_sample_warning: str
    strategy_registry_status: str  # read-only cross-reference, e.g. "NOT_READY" -- never set by this module


def _trading_stats(trades: Sequence[PaperExperimentTradeRecord]) -> TradingStatsReport:
    closed = [t for t in trades if t.net_pnl_usd is not None]
    wins = [t for t in closed if t.net_pnl_usd > 0]
    losses = [t for t in closed if t.net_pnl_usd < 0]
    win_rate = len(wins) / len(closed) if closed else None
    avg_win = sum(t.net_pnl_usd for t in wins) / len(wins) if wins else None
    avg_loss = sum(t.net_pnl_usd for t in losses) / len(losses) if losses else None
    expectancy = None
    if win_rate is not None and avg_win is not None and avg_loss is not None:
        expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss
    profit_factor = None
    if losses:
        gross_win = sum(t.net_pnl_usd for t in wins)
        gross_loss = abs(sum(t.net_pnl_usd for t in losses))
        profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None
    holding_minutes = [
        (t.exit_timestamp - t.entry_timestamp).total_seconds() / 60 for t in closed if t.exit_timestamp is not None
    ]
    avg_holding = sum(holding_minutes) / len(holding_minutes) if holding_minutes else None
    return TradingStatsReport(
        total_trades=len(closed), winning_trades=len(wins), losing_trades=len(losses), win_rate=win_rate,
        average_win_usd=avg_win, average_loss_usd=avg_loss, expectancy_usd=expectancy, profit_factor=profit_factor,
        average_holding_minutes=avg_holding,
    )


def _execution_quality(trades: Sequence[PaperExperimentTradeRecord], *, no_executable_quote_count: int = 0, missing_quote_count: int = 0) -> ExecutionQualityReport:
    closed = [t for t in trades if t.net_pnl_usd is not None]
    spreads = [t.spread_cost_usd for t in closed if t.spread_cost_usd is not None]
    slippages = [t.slippage_usd for t in closed if t.slippage_usd is not None]
    fees = sum(t.fees_usd for t in closed if t.fees_usd is not None)
    return ExecutionQualityReport(
        average_quoted_spread_usd=(sum(spreads) / len(spreads)) if spreads else None,
        average_slippage_usd=(sum(slippages) / len(slippages)) if slippages else None,
        total_fees_usd=round(fees, 2), rejected_fills=no_executable_quote_count, missing_quotes=missing_quote_count,
        execution_quality_failures=no_executable_quote_count + missing_quote_count,
    )


def _portfolio(trades: Sequence[PaperExperimentTradeRecord], equity_curve: Sequence[EquitySnapshotRecord]) -> PortfolioReport:
    exposures = [e.open_exposure_usd for e in equity_curve]
    max_exposure = max(exposures, default=0.0)
    avg_exposure = (sum(exposures) / len(exposures)) if exposures else 0.0
    position_sizes = [
        (t.entry_fill or 0.0) * t.quantity * 100 for t in trades if t.entry_fill is not None
    ]
    largest_position = max(position_sizes, default=0.0)
    symbol_totals: dict[str, float] = {}
    for t, size in zip(trades, position_sizes):
        symbol_totals[t.symbol] = symbol_totals.get(t.symbol, 0.0) + size
    max_symbol = max(symbol_totals, key=symbol_totals.get) if symbol_totals else None
    total_size = sum(symbol_totals.values())
    max_pct = (symbol_totals[max_symbol] / total_size) if max_symbol and total_size > 0 else None
    return PortfolioReport(
        max_exposure_usd=round(max_exposure, 2), average_exposure_usd=round(avg_exposure, 2),
        largest_position_usd=round(largest_position, 2), max_concentration_symbol=max_symbol,
        max_concentration_pct=max_pct, unique_contracts_traded=len({t.option_id for t in trades}),
    )


def build_final_report(
    *, config: ExperimentConfig, experiment_status: str, calendar_days_elapsed: int, market_days_observed: int,
    trades: Sequence[PaperExperimentTradeRecord], equity_curve: Sequence[EquitySnapshotRecord],
    latest_snapshot: PaperExperimentAccountSnapshot | None, strategy_registry_status: str,
    no_executable_quote_count: int = 0, missing_quote_count: int = 0,
) -> FinalExperimentReport:
    daily = compute_daily_performance(equity_curve, trades)
    equities = [e.equity_usd for e in equity_curve]
    return FinalExperimentReport(
        config=config, experiment_status=experiment_status, calendar_days_elapsed=calendar_days_elapsed,
        market_days_observed=market_days_observed, starting_capital_usd=config.starting_capital_usd,
        ending_equity_usd=(latest_snapshot.equity_usd if latest_snapshot else None),
        net_pnl_usd=(round(latest_snapshot.equity_usd - config.starting_capital_usd, 2) if latest_snapshot else None),
        total_return_pct=(latest_snapshot.total_return_pct if latest_snapshot else None),
        max_drawdown_pct=(max((e.drawdown_pct for e in equity_curve), default=None) if equity_curve else None),
        peak_equity_usd=(max(equities) if equities else None), lowest_equity_usd=(min(equities) if equities else None),
        trading=_trading_stats(trades), execution=_execution_quality(trades, no_executable_quote_count=no_executable_quote_count, missing_quote_count=missing_quote_count),
        portfolio=_portfolio(trades, equity_curve), daily_performance=tuple(daily), equity_curve=tuple(equity_curve),
        small_sample_warning=MINIMUM_SAMPLE_WARNING, strategy_registry_status=strategy_registry_status,
    )
