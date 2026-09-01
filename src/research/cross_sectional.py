"""Subgroup analysis (Phase 5, section 9): does a strategy's aggregate
result depend on a small number of securities, one year, or one regime?
Every breakdown here operates on an already-computed BacktestTrade list —
no re-simulation, just honest attribution of the SAME result.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from src.backtesting.journal import BacktestTrade
from src.backtesting.metrics import PerformanceMetrics, compute_performance_metrics
from src.data.universe import Universe
from src.research.analysis import mean, stdev


@dataclass(frozen=True)
class SubgroupResult:
    key: str
    trade_count: int
    net_pnl_total: float
    metrics: PerformanceMetrics


def _metrics_for(trades: Sequence[BacktestTrade], starting_cash: float) -> PerformanceMetrics:
    return compute_performance_metrics(equity_curve=[], trades=list(trades), starting_cash=starting_cash)


def by_symbol(trades: Sequence[BacktestTrade], *, starting_cash: float) -> dict[str, SubgroupResult]:
    buckets: dict[str, list[BacktestTrade]] = defaultdict(list)
    for t in trades:
        buckets[t.symbol].append(t)
    return {sym: SubgroupResult(sym, len(ts), sum(t.net_pnl for t in ts), _metrics_for(ts, starting_cash)) for sym, ts in buckets.items()}


def by_sector(trades: Sequence[BacktestTrade], universe: Universe, *, starting_cash: float) -> dict[str, SubgroupResult]:
    buckets: dict[str, list[BacktestTrade]] = defaultdict(list)
    for t in trades:
        sector = universe.sector_of(t.symbol) or "unclassified"
        buckets[sector].append(t)
    return {sec: SubgroupResult(sec, len(ts), sum(t.net_pnl for t in ts), _metrics_for(ts, starting_cash)) for sec, ts in buckets.items()}


def by_year(trades: Sequence[BacktestTrade], *, starting_cash: float) -> dict[str, SubgroupResult]:
    buckets: dict[str, list[BacktestTrade]] = defaultdict(list)
    for t in trades:
        buckets[str(t.entry_timestamp.year)].append(t)
    return {yr: SubgroupResult(yr, len(ts), sum(t.net_pnl for t in ts), _metrics_for(ts, starting_cash)) for yr, ts in sorted(buckets.items())}


def by_volatility_bucket(
    trades: Sequence[BacktestTrade], realized_vol_by_symbol: Mapping[str, float], *, starting_cash: float, n_buckets: int = 3
) -> dict[str, SubgroupResult]:
    """Buckets trades by their SYMBOL's overall realized volatility
    (caller supplies one pre-computed volatility figure per symbol — e.g.
    the full-period stdev of daily returns — so this module never
    computes anything using future information itself). Market-cap
    bucketing (also requested in section 9) is NOT implemented: no market
    -cap data is available anywhere in this codebase's data sources —
    documented as a limitation rather than fabricated."""
    ranked_symbols = sorted(realized_vol_by_symbol, key=lambda s: realized_vol_by_symbol[s])
    n = len(ranked_symbols)
    bucket_of: dict[str, str] = {}
    for i, sym in enumerate(ranked_symbols):
        idx = min(n_buckets - 1, (i * n_buckets) // n) if n else 0
        bucket_of[sym] = f"vol_bucket_{idx + 1}_of_{n_buckets}"

    buckets: dict[str, list[BacktestTrade]] = defaultdict(list)
    for t in trades:
        buckets[bucket_of.get(t.symbol, "unclassified")].append(t)
    return {b: SubgroupResult(b, len(ts), sum(t.net_pnl for t in ts), _metrics_for(ts, starting_cash)) for b, ts in buckets.items()}


def concentration_summary(trades: Sequence[BacktestTrade]) -> dict[str, float]:
    """What fraction of TOTAL net P&L came from each symbol — the direct
    answer to "did 10 symbols carry the whole result while 90 lost
    money" (section 9's worked example)."""
    total = sum(t.net_pnl for t in trades)
    per_symbol: dict[str, float] = defaultdict(float)
    for t in trades:
        per_symbol[t.symbol] += t.net_pnl
    if total == 0:
        return {sym: 0.0 for sym in per_symbol}
    return {sym: pnl / total for sym, pnl in per_symbol.items()}
