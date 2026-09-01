"""Performance analytics (Phase 3, section 14). Pure stdlib — no
numpy/pandas/scipy, consistent with this project's zero-third-party-
dependency convention (see src/features/_util.py, src/research/analysis.py
for the same pattern).

Every ratio here assumes a 0% risk-free rate (not netted out anywhere) —
documented rather than silently assumed away.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from src.backtesting.journal import BacktestTrade
from src.backtesting.portfolio import EquityPoint


@dataclass(frozen=True)
class ReturnStatistics:
    total_return_pct: float
    annualized_return_pct: float | None
    cagr_pct: float | None
    volatility_annualized_pct: float | None
    sharpe_ratio: float | None
    sortino_ratio: float | None
    calmar_ratio: float | None


@dataclass(frozen=True)
class DrawdownStatistics:
    max_drawdown_usd: float
    max_drawdown_pct: float
    average_drawdown_pct: float
    max_drawdown_duration_bars: int


@dataclass(frozen=True)
class TradeStatistics:
    trade_count: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    average_win: float
    average_loss: float
    largest_win: float
    largest_loss: float
    profit_factor: float | None
    expectancy: float
    average_holding_period_minutes: float


@dataclass(frozen=True)
class PortfolioStatistics:
    average_exposure_pct: float
    max_exposure_pct: float
    turnover: float
    max_concurrent_positions: int
    max_concentration_pct: float | None


@dataclass(frozen=True)
class LossAnalysis:
    max_losing_streak: int
    worst_day_pct: float | None
    worst_week_pct: float | None
    worst_month_pct: float | None
    tail_loss_avg_pct: float | None  # average of the worst 5% of per-bar returns


@dataclass(frozen=True)
class BenchmarkComparison:
    benchmark_symbol: str
    benchmark_total_return_pct: float
    strategy_total_return_pct: float
    excess_return_pct: float
    benchmark_sharpe: float | None
    strategy_sharpe: float | None


@dataclass(frozen=True)
class PerformanceMetrics:
    returns: ReturnStatistics
    drawdown: DrawdownStatistics
    trades: TradeStatistics
    portfolio: PortfolioStatistics
    loss_analysis: LossAnalysis
    benchmark: BenchmarkComparison | None = None


def _period_returns(equity_curve: list[EquityPoint]) -> list[float]:
    out = []
    for prev, cur in zip(equity_curve, equity_curve[1:]):
        if prev.equity > 0:
            out.append((cur.equity - prev.equity) / prev.equity)
    return out


def _resample_daily(equity_curve: list[EquityPoint]) -> list[tuple[date, float]]:
    """Last equity value per calendar date, in chronological order."""
    by_date: dict[date, float] = {}
    for point in equity_curve:
        by_date[point.timestamp.date()] = point.equity
    return sorted(by_date.items())


def _sharpe(returns: list[float], periods_per_year: float) -> float | None:
    if len(returns) < 2:
        return None
    mean = statistics.mean(returns)
    stdev = statistics.stdev(returns)
    if stdev == 0:
        return None
    return (mean / stdev) * math.sqrt(periods_per_year)


def _sortino(returns: list[float], periods_per_year: float) -> float | None:
    if len(returns) < 2:
        return None
    mean = statistics.mean(returns)
    downside = [r for r in returns if r < 0]
    if len(downside) < 2:
        return None
    downside_dev = statistics.stdev(downside)
    if downside_dev == 0:
        return None
    return (mean / downside_dev) * math.sqrt(periods_per_year)


def _max_drawdown_duration_bars(equity_curve: list[EquityPoint]) -> int:
    longest = current = 0
    for point in equity_curve:
        if point.drawdown_pct < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _compute_returns(equity_curve: list[EquityPoint], starting_cash: float, periods_per_year: float) -> ReturnStatistics:
    if not equity_curve or starting_cash <= 0:
        return ReturnStatistics(0.0, None, None, None, None, None, None)

    final_equity = equity_curve[-1].equity
    total_return = (final_equity - starting_cash) / starting_cash

    elapsed = equity_curve[-1].timestamp - equity_curve[0].timestamp
    years = elapsed.total_seconds() / (365.25 * 24 * 3600)
    cagr = None
    annualized_return = None
    if years > 0 and final_equity > 0:
        cagr = (final_equity / starting_cash) ** (1 / years) - 1
        annualized_return = cagr  # same figure for a single unbroken equity series

    daily = [eq for _d, eq in _resample_daily(equity_curve)]
    daily_returns = [(daily[i] - daily[i - 1]) / daily[i - 1] for i in range(1, len(daily)) if daily[i - 1] > 0]

    volatility = statistics.stdev(daily_returns) * math.sqrt(252) if len(daily_returns) >= 2 else None
    sharpe = _sharpe(daily_returns, 252)
    sortino = _sortino(daily_returns, 252)

    max_dd_pct = min((p.drawdown_pct for p in equity_curve), default=0.0)
    calmar = (cagr / abs(max_dd_pct)) if cagr is not None and max_dd_pct != 0 else None

    return ReturnStatistics(
        total_return_pct=total_return * 100,
        annualized_return_pct=annualized_return * 100 if annualized_return is not None else None,
        cagr_pct=cagr * 100 if cagr is not None else None,
        volatility_annualized_pct=volatility * 100 if volatility is not None else None,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
    )


def _compute_drawdown(equity_curve: list[EquityPoint]) -> DrawdownStatistics:
    if not equity_curve:
        return DrawdownStatistics(0.0, 0.0, 0.0, 0)
    max_dd_usd = min((p.drawdown for p in equity_curve), default=0.0)
    max_dd_pct = min((p.drawdown_pct for p in equity_curve), default=0.0)
    in_drawdown = [p.drawdown_pct for p in equity_curve if p.drawdown_pct < 0]
    avg_dd_pct = statistics.mean(in_drawdown) if in_drawdown else 0.0
    duration = _max_drawdown_duration_bars(equity_curve)
    return DrawdownStatistics(
        max_drawdown_usd=max_dd_usd,
        max_drawdown_pct=max_dd_pct * 100,
        average_drawdown_pct=avg_dd_pct * 100,
        max_drawdown_duration_bars=duration,
    )


def _compute_trades(trades: list[BacktestTrade]) -> TradeStatistics:
    if not trades:
        return TradeStatistics(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, None, 0.0, 0.0)
    winning = [t for t in trades if t.net_pnl > 0]
    losing = [t for t in trades if t.net_pnl <= 0]
    gross_profit = sum(t.net_pnl for t in winning)
    gross_loss = sum(t.net_pnl for t in losing)
    profit_factor = (gross_profit / abs(gross_loss)) if gross_loss != 0 else None
    return TradeStatistics(
        trade_count=len(trades),
        winning_trades=len(winning),
        losing_trades=len(losing),
        win_rate=len(winning) / len(trades),
        average_win=statistics.mean([t.net_pnl for t in winning]) if winning else 0.0,
        average_loss=statistics.mean([t.net_pnl for t in losing]) if losing else 0.0,
        largest_win=max((t.net_pnl for t in winning), default=0.0),
        largest_loss=min((t.net_pnl for t in losing), default=0.0),
        profit_factor=profit_factor,
        expectancy=statistics.mean([t.net_pnl for t in trades]),
        average_holding_period_minutes=statistics.mean([t.holding_period_minutes for t in trades]),
    )


def _compute_portfolio(equity_curve: list[EquityPoint], trades: list[BacktestTrade]) -> PortfolioStatistics:
    if not equity_curve:
        return PortfolioStatistics(0.0, 0.0, 0.0, 0, None)
    exposures = [p.positions_value / p.equity if p.equity > 0 else 0.0 for p in equity_curve]
    max_concurrent = max((p.open_position_count for p in equity_curve), default=0)
    all_weights = [w for p in equity_curve for w in p.position_weights.values()]
    max_concentration = max(all_weights) * 100 if all_weights else None
    turnover_notional = sum(t.quantity * t.entry_price + t.quantity * t.exit_price for t in trades)
    avg_equity = statistics.mean([p.equity for p in equity_curve]) if equity_curve else 0.0
    turnover = (turnover_notional / avg_equity) if avg_equity > 0 else 0.0
    return PortfolioStatistics(
        average_exposure_pct=statistics.mean(exposures) * 100,
        max_exposure_pct=max(exposures) * 100,
        turnover=turnover,
        max_concurrent_positions=max_concurrent,
        max_concentration_pct=max_concentration,
    )


def _compute_loss_analysis(equity_curve: list[EquityPoint], trades: list[BacktestTrade]) -> LossAnalysis:
    max_streak = streak = 0
    for t in trades:
        if t.net_pnl <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    daily = _resample_daily(equity_curve)
    daily_returns_by_date = [
        (daily[i][0], (daily[i][1] - daily[i - 1][1]) / daily[i - 1][1]) for i in range(1, len(daily)) if daily[i - 1][1] > 0
    ]
    worst_day = min((r for _d, r in daily_returns_by_date), default=None)

    weekly: dict[tuple[int, int], float] = {}
    for d, eq in daily:
        weekly[d.isocalendar()[:2]] = eq  # last value per (iso_year, iso_week) wins, since `daily` is sorted
    weekly_sorted = sorted(weekly.items())
    weekly_returns = [
        (weekly_sorted[i][1] - weekly_sorted[i - 1][1]) / weekly_sorted[i - 1][1]
        for i in range(1, len(weekly_sorted))
        if weekly_sorted[i - 1][1] > 0
    ]
    worst_week = min(weekly_returns, default=None)

    monthly: dict[tuple[int, int], float] = {}
    for d, eq in daily:
        monthly[(d.year, d.month)] = eq
    monthly_sorted = sorted(monthly.items())
    monthly_returns = [
        (monthly_sorted[i][1] - monthly_sorted[i - 1][1]) / monthly_sorted[i - 1][1]
        for i in range(1, len(monthly_sorted))
        if monthly_sorted[i - 1][1] > 0
    ]
    worst_month = min(monthly_returns, default=None)

    period_returns = sorted(_period_returns(equity_curve))
    tail_loss = None
    if period_returns:
        tail_n = max(1, round(len(period_returns) * 0.05))
        tail_loss = statistics.mean(period_returns[:tail_n]) * 100

    return LossAnalysis(
        max_losing_streak=max_streak,
        worst_day_pct=worst_day * 100 if worst_day is not None else None,
        worst_week_pct=worst_week * 100 if worst_week is not None else None,
        worst_month_pct=worst_month * 100 if worst_month is not None else None,
        tail_loss_avg_pct=tail_loss,
    )


def compute_benchmark_comparison(
    *, benchmark_symbol: str, benchmark_curve: list[EquityPoint], strategy_curve: list[EquityPoint], starting_cash: float
) -> BenchmarkComparison | None:
    if not benchmark_curve or not strategy_curve or starting_cash <= 0:
        return None
    benchmark_return = (benchmark_curve[-1].equity - starting_cash) / starting_cash
    strategy_return = (strategy_curve[-1].equity - starting_cash) / starting_cash
    benchmark_daily = [eq for _d, eq in _resample_daily(benchmark_curve)]
    strategy_daily = [eq for _d, eq in _resample_daily(strategy_curve)]
    benchmark_returns = [
        (benchmark_daily[i] - benchmark_daily[i - 1]) / benchmark_daily[i - 1]
        for i in range(1, len(benchmark_daily))
        if benchmark_daily[i - 1] > 0
    ]
    strategy_returns = [
        (strategy_daily[i] - strategy_daily[i - 1]) / strategy_daily[i - 1]
        for i in range(1, len(strategy_daily))
        if strategy_daily[i - 1] > 0
    ]
    return BenchmarkComparison(
        benchmark_symbol=benchmark_symbol,
        benchmark_total_return_pct=benchmark_return * 100,
        strategy_total_return_pct=strategy_return * 100,
        excess_return_pct=(strategy_return - benchmark_return) * 100,
        benchmark_sharpe=_sharpe(benchmark_returns, 252),
        strategy_sharpe=_sharpe(strategy_returns, 252),
    )


def compute_performance_metrics(
    *,
    equity_curve: list[EquityPoint],
    trades: list[BacktestTrade],
    starting_cash: float,
    periods_per_year: float = 252.0,
    benchmark: BenchmarkComparison | None = None,
) -> PerformanceMetrics:
    return PerformanceMetrics(
        returns=_compute_returns(equity_curve, starting_cash, periods_per_year),
        drawdown=_compute_drawdown(equity_curve),
        trades=_compute_trades(trades),
        portfolio=_compute_portfolio(equity_curve, trades),
        loss_analysis=_compute_loss_analysis(equity_curve, trades),
        benchmark=benchmark,
    )
