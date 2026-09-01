"""Leave-one-symbol-out analysis (Phase 5, section 10).

Methodology, stated explicitly: this operates POST-HOC on an already-
computed BacktestTrade list — filtering out one symbol's trades and
recomputing aggregate metrics on what remains — rather than re-running N
separate simulations with that symbol excluded from the universe. This is
the standard, much cheaper approach for a concentration/attribution
question ("does removing symbol X change the conclusion") and is exactly
correct for it; it is NOT identical to re-simulating with a smaller
universe (which could, in principle, change shared-cash-constrained risk
decisions for the OTHER symbols) — that distinction is documented here
rather than glossed over.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.backtesting.journal import BacktestTrade
from src.backtesting.metrics import PerformanceMetrics, compute_performance_metrics


@dataclass(frozen=True)
class LeaveOneOutResult:
    excluded_key: str  # symbol (or group label) left out
    remaining_trade_count: int
    metrics_without: PerformanceMetrics


@dataclass(frozen=True)
class LeaveOneOutReport:
    full_metrics: PerformanceMetrics
    results: tuple[LeaveOneOutResult, ...]

    @property
    def max_expectancy_swing(self) -> float | None:
        """The largest change in expectancy caused by removing any single
        symbol — a large swing means the full-universe result leans
        heavily on that one symbol."""
        if not self.results or self.full_metrics.trades.trade_count == 0:
            return None
        full = self.full_metrics.trades.expectancy
        return max(abs(r.metrics_without.trades.expectancy - full) for r in self.results)

    @property
    def sign_flips_without(self) -> tuple[str, ...]:
        """Symbols whose removal flips the aggregate expectancy from
        positive to non-positive or vice versa — section 10's explicit
        "do not classify as robust if one security dominates" check."""
        full_positive = self.full_metrics.trades.expectancy > 0
        return tuple(r.excluded_key for r in self.results if (r.metrics_without.trades.expectancy > 0) != full_positive)


def leave_one_symbol_out(trades: Sequence[BacktestTrade], *, starting_cash: float) -> LeaveOneOutReport:
    trades = list(trades)
    full_metrics = compute_performance_metrics(equity_curve=[], trades=trades, starting_cash=starting_cash)
    symbols = sorted({t.symbol for t in trades})
    results = []
    for symbol in symbols:
        remaining = [t for t in trades if t.symbol != symbol]
        metrics = compute_performance_metrics(equity_curve=[], trades=remaining, starting_cash=starting_cash)
        results.append(LeaveOneOutResult(excluded_key=symbol, remaining_trade_count=len(remaining), metrics_without=metrics))
    return LeaveOneOutReport(full_metrics=full_metrics, results=tuple(results))


def leave_one_group_out(trades: Sequence[BacktestTrade], groups: dict[str, tuple[str, ...]], *, starting_cash: float) -> LeaveOneOutReport:
    """Same idea, but removing an entire GROUP of symbols at once (e.g.
    one sector) — for when the universe is large enough that single-
    symbol leave-one-out is too fine-grained to be informative."""
    trades = list(trades)
    full_metrics = compute_performance_metrics(equity_curve=[], trades=trades, starting_cash=starting_cash)
    results = []
    for group_name, group_symbols in groups.items():
        remaining = [t for t in trades if t.symbol not in group_symbols]
        metrics = compute_performance_metrics(equity_curve=[], trades=remaining, starting_cash=starting_cash)
        results.append(LeaveOneOutResult(excluded_key=group_name, remaining_trade_count=len(remaining), metrics_without=metrics))
    return LeaveOneOutReport(full_metrics=full_metrics, results=tuple(results))
