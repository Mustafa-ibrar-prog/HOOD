"""Phase 6, section 10: the distribution of trade returns — is the
result a broad, unremarkable-looking distribution, or a handful of
outsized trades doing all the work? Pure stdlib (`statistics`), same
zero-third-party-dependency convention as src/backtesting/metrics.py.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Sequence

from src.backtesting.journal import BacktestTrade
from src.research.cross_sectional import concentration_summary


@dataclass(frozen=True)
class TradeReturnDistribution:
    trade_count: int
    mean: float
    median: float
    stdev: float | None
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float
    pct_pnl_from_top_1pct_trades: float | None
    pct_pnl_from_top_5pct_trades: float | None
    largest_contributing_symbol: str | None
    pct_pnl_from_largest_contributing_symbol: float | None


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (the same convention `statistics.quantiles`
    uses internally) — no numpy, consistent with this project's stdlib-only rule."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * pct
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def trade_return_distribution(trades: Sequence[BacktestTrade]) -> TradeReturnDistribution:
    if not trades:
        return TradeReturnDistribution(0, 0.0, 0.0, None, 0.0, 0.0, 0.0, 0.0, 0.0, None, None, None, None)

    values = [t.net_pnl for t in trades]
    sorted_values = sorted(values)
    total = sum(values)

    top_1pct_n = max(1, round(len(sorted_values) * 0.01))
    top_5pct_n = max(1, round(len(sorted_values) * 0.05))
    top_1pct_sum = sum(sorted(values, reverse=True)[:top_1pct_n])
    top_5pct_sum = sum(sorted(values, reverse=True)[:top_5pct_n])

    conc = concentration_summary(trades)
    largest_symbol = max(conc, key=lambda s: abs(conc[s])) if conc else None

    return TradeReturnDistribution(
        trade_count=len(trades),
        mean=statistics.mean(values),
        median=statistics.median(values),
        stdev=statistics.stdev(values) if len(values) >= 2 else None,
        p5=_percentile(sorted_values, 0.05), p25=_percentile(sorted_values, 0.25),
        p50=_percentile(sorted_values, 0.50), p75=_percentile(sorted_values, 0.75),
        p95=_percentile(sorted_values, 0.95),
        pct_pnl_from_top_1pct_trades=(top_1pct_sum / total * 100) if total != 0 else None,
        pct_pnl_from_top_5pct_trades=(top_5pct_sum / total * 100) if total != 0 else None,
        largest_contributing_symbol=largest_symbol,
        pct_pnl_from_largest_contributing_symbol=(conc[largest_symbol] * 100) if largest_symbol is not None else None,
    )
