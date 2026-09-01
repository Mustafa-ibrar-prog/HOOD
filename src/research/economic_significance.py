"""Phase 7, Part 6: economic significance — a statistically significant
effect is not automatically tradable. Reuses src.backtesting.metrics'
already-computed PerformanceMetrics/TradeStatistics wherever possible
rather than recomputing Sharpe/Sortino/Calmar/drawdown/profit-factor/win-
rate from scratch (this module only adds what Phase 3's metrics module
does NOT already compute: gross-vs-net split, turnover-derived cost
estimates, edge/cost ratio, cost-multiplier sensitivity, payoff ratio,
and a capacity proxy).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.backtesting.journal import BacktestTrade
from src.backtesting.metrics import PerformanceMetrics


@dataclass(frozen=True)
class EconomicSignificanceReport:
    trade_count: int
    gross_expectancy: float
    net_expectancy: float
    turnover: float | None  # from PerformanceMetrics.portfolio.turnover, if an equity curve was available
    total_fees: float
    total_slippage_informational: float  # informational only — see src.backtesting.engine: slippage is already baked into gross_pnl via the fill price, NOT a second deduction from net_pnl
    average_holding_period_minutes: float
    trade_frequency_per_year: float | None  # trades / (span in years), None if span is degenerate
    capacity_proxy_usd: float | None  # a rough, documented lower-bound proxy — see compute_capacity_proxy
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    profit_factor: float | None
    win_rate: float
    payoff_ratio: float | None  # average_win / |average_loss|
    cost_to_edge_ratio: float | None  # total costs (fees) / |gross P&L|  — how much of the edge costs eat
    edge_cost_ratio: float | None  # the inverse framing requested by Part 6: net edge per $1 of cost

    def render(self) -> str:
        lines = [
            "ECONOMIC SIGNIFICANCE",
            f"  trades={self.trade_count}  gross_expectancy=${self.gross_expectancy:.2f}/trade  net_expectancy=${self.net_expectancy:.2f}/trade",
            f"  total_fees=${self.total_fees:.2f}  total_slippage(informational)=${self.total_slippage_informational:.2f}",
            f"  avg_holding_period={self.average_holding_period_minutes:.1f} min  trade_frequency/yr={self.trade_frequency_per_year}",
            f"  capacity_proxy_usd={self.capacity_proxy_usd}",
            f"  Sharpe={self.sharpe}  Sortino={self.sortino}  Calmar={self.calmar}  profit_factor={self.profit_factor}",
            f"  win_rate={self.win_rate:.2%}  payoff_ratio={self.payoff_ratio}",
            f"  cost_to_edge_ratio={self.cost_to_edge_ratio}  edge_cost_ratio={self.edge_cost_ratio}",
        ]
        return "\n".join(lines)


def compute_capacity_proxy(trades: Sequence[BacktestTrade], *, participation_rate: float = 0.01) -> float | None:
    """A DELIBERATELY ROUGH lower-bound proxy for how much capital this
    strategy's edge could plausibly absorb before its own trading starts
    moving prices: assumes each trade could safely represent up to
    `participation_rate` (default 1%) of that trade's own notional
    without materially changing the fill price it already got (this is a
    proxy, not a market-impact model — this codebase has no volume/ADV
    data pipeline to do better). Returns the SMALLEST such implied
    capacity across all trades (the binding constraint), or None if there
    are no trades."""
    if not trades:
        return None
    implied = [abs(t.quantity * t.entry_price) / participation_rate for t in trades if t.entry_price > 0]
    if not implied:
        return None
    return min(implied)


def evaluate_economic_significance(
    *, trades: Sequence[BacktestTrade], metrics: PerformanceMetrics, span_years: float | None = None, participation_rate: float = 0.01,
) -> EconomicSignificanceReport:
    n = len(trades)
    gross_total = sum(t.gross_pnl for t in trades)
    net_total = sum(t.net_pnl for t in trades)
    fees_total = sum(t.fees for t in trades)
    slippage_total = sum(t.slippage for t in trades)

    gross_expectancy = gross_total / n if n else 0.0
    net_expectancy = net_total / n if n else 0.0
    trade_frequency = (n / span_years) if span_years and span_years > 0 else None

    avg_win = metrics.trades.average_win
    avg_loss = metrics.trades.average_loss
    payoff_ratio = (avg_win / abs(avg_loss)) if avg_loss != 0 else None

    cost_to_edge = (fees_total / abs(gross_total)) if gross_total != 0 else None
    edge_cost = (net_expectancy / (fees_total / n)) if n and fees_total > 0 else None

    return EconomicSignificanceReport(
        trade_count=n, gross_expectancy=gross_expectancy, net_expectancy=net_expectancy,
        turnover=metrics.portfolio.turnover if metrics.portfolio.turnover else None,
        total_fees=fees_total, total_slippage_informational=slippage_total,
        average_holding_period_minutes=metrics.trades.average_holding_period_minutes,
        trade_frequency_per_year=trade_frequency, capacity_proxy_usd=compute_capacity_proxy(trades, participation_rate=participation_rate),
        sharpe=metrics.returns.sharpe_ratio, sortino=metrics.returns.sortino_ratio, calmar=metrics.returns.calmar_ratio,
        profit_factor=metrics.trades.profit_factor, win_rate=metrics.trades.win_rate, payoff_ratio=payoff_ratio,
        cost_to_edge_ratio=cost_to_edge, edge_cost_ratio=edge_cost,
    )


@dataclass(frozen=True)
class CostStressPoint:
    cost_multiplier: float
    net_pnl_total: float
    net_expectancy: float
    edge_survives: bool


@dataclass(frozen=True)
class CostStressReport:
    points: tuple[CostStressPoint, ...]

    def render(self) -> str:
        lines = ["EXPECTED NET EDGE AFTER 1x / 2x / 3x COSTS"]
        for p in self.points:
            lines.append(f"  {p.cost_multiplier}x: net_pnl_total=${p.net_pnl_total:.2f}  net_expectancy=${p.net_expectancy:.2f}/trade  edge_survives={p.edge_survives}")
        return "\n".join(lines)


def cost_multiplier_edge(trades: Sequence[BacktestTrade], *, multipliers: Sequence[float] = (1.0, 2.0, 3.0)) -> CostStressReport:
    """A lightweight, POST-HOC cost-stress view (does not re-run a
    backtest — see src.research.validation.run_cost_sensitivity for the
    real re-simulated version): scales each trade's RECORDED fees by the
    multiplier and recomputes net P&L, i.e. `gross_pnl - fees*multiplier`
    (see src.backtesting.engine: net_pnl = gross_pnl - fees; slippage is
    already inside gross_pnl via the fill price and is NOT separately
    scaled here — scaling it too would double-count an execution
    assumption change that a real re-simulation, not a post-hoc
    recompute, is needed to model honestly)."""
    n = len(trades)
    points = []
    for m in multipliers:
        total = sum(t.gross_pnl - t.fees * m for t in trades)
        points.append(CostStressPoint(cost_multiplier=m, net_pnl_total=total, net_expectancy=(total / n) if n else 0.0, edge_survives=total > 0))
    return CostStressReport(points=tuple(points))
