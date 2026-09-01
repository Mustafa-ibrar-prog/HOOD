"""Regime analysis (Phase 4, section 12).

Regime labels are computed by src.features.regime (TrendRegime,
VolatilityRegime, MomentumRegime — all causal by construction, already
tested for no-future-data leakage in Phase 2). This module only buckets
already-generated BacktestTrade records (Phase 3) by the regime active AT
EACH TRADE'S ENTRY TIMESTAMP, and reuses Phase 3's public
compute_performance_metrics() per bucket — no duplicated metrics logic.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from src.backtesting.journal import BacktestTrade
from src.backtesting.metrics import PerformanceMetrics, compute_performance_metrics
from src.data.bar import Bar
from src.features.engine import FeatureEngine
from src.features.regime import TrendRegime, VolatilityRegime


def label_bars_by_regime(
    bars: Sequence[Bar], *, fast_window: int = 10, slow_window: int = 50, vol_window: int = 20, vol_lookback: int = 100
) -> dict[datetime, str]:
    """Causal per-bar regime label, one of: "bull_low_vol", "bull_high_vol",
    "bear_low_vol", "bear_high_vol", "sideways", or "unknown" (insufficient
    history for either feature yet). Uses ONLY src.features.regime's
    already-causal TrendRegime/VolatilityRegime — computed once, over the
    full bar series, exactly like any other Phase 2 feature."""
    engine = FeatureEngine([TrendRegime(fast_window, slow_window), VolatilityRegime(vol_window, vol_lookback, 5)])
    frame = engine.compute(bars)
    trend_col = f"trend_regime_{fast_window}_{slow_window}"
    vol_col = f"vol_regime_{vol_window}_{vol_lookback}_5"

    labels: dict[datetime, str] = {}
    for i, ts in enumerate(frame.timestamps):
        trend = frame.columns[trend_col][i]
        vol = frame.columns[vol_col][i]
        if trend is None or vol is None:
            labels[ts] = "unknown"
            continue
        vol_label = "low_vol" if vol <= 1 else "high_vol"
        if trend == 1.0:
            labels[ts] = f"bull_{vol_label}"
        elif trend == -1.0:
            labels[ts] = f"bear_{vol_label}"
        else:
            labels[ts] = "sideways"
    return labels


def bucket_trades_by_regime(trades: Sequence[BacktestTrade], regime_by_timestamp: dict[datetime, str]) -> dict[str, list[BacktestTrade]]:
    """Buckets by the regime active at ENTRY — a trade's classification is
    fixed at the moment it was opened, never revised using what happened
    during the trade (which would itself be a form of look-ahead)."""
    buckets: dict[str, list[BacktestTrade]] = defaultdict(list)
    for trade in trades:
        label = regime_by_timestamp.get(trade.entry_timestamp, "unknown")
        buckets[label].append(trade)
    return dict(buckets)


def regime_performance_report(trades_by_regime: dict[str, list[BacktestTrade]], *, starting_cash: float) -> dict[str, PerformanceMetrics]:
    """Per-regime trade statistics (return/vol/Sharpe/drawdown/trade
    count/win rate/profit factor) — an empty equity_curve is passed since
    a per-regime bucket of scattered trades has no continuous equity
    series of its own; PerformanceMetrics.trades (win rate, profit
    factor, expectancy, ...) is what's meaningful here, not the
    equity-curve-derived Sharpe/drawdown fields, which will read as
    None/0 for an empty curve — documented, not hidden."""
    return {
        regime: compute_performance_metrics(equity_curve=[], trades=trades, starting_cash=starting_cash)
        for regime, trades in trades_by_regime.items()
    }
