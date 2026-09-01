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

from typing import Mapping

from src.backtesting.journal import BacktestTrade
from src.backtesting.metrics import PerformanceMetrics, compute_performance_metrics
from src.data.bar import Bar
from src.features.engine import FeatureEngine
from src.features.regime import TrendRegime, VolatilityRegime
from src.research.ic import ICSummary, compute_ic_series, summarize_ic


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


def ic_by_regime(
    panel_rows: list[dict], feature_col: str, target_col: str, regime_by_timestamp: Mapping[datetime, str], *, min_universe_size: int = 3,
) -> dict[str, ICSummary]:
    """Phase 7, Part 9: cross-sectional IC bucketed by regime — the
    forward reference src.research.ic's module docstring has pointed to
    since Phase 4 ("Regime-based bucketing ... see
    src.research.regime.ic_by_regime") and Part 9's explicit requirement
    ("distinguish 'works in most regimes' from 'works only in one narrow
    regime'"). Buckets each panel row by the regime active AT THAT ROW'S
    OWN timestamp (never a later regime — a row is bucketed using only
    information available causally at its own timestamp, same principle
    as bucket_trades_by_regime above), then runs Phase 4's
    compute_ic_series/summarize_ic independently within each bucket."""
    buckets: dict[str, list[dict]] = {}
    for row in panel_rows:
        label = regime_by_timestamp.get(row["timestamp"], "unknown")
        buckets.setdefault(label, []).append(row)
    return {
        regime: summarize_ic(compute_ic_series(rows, feature_col, target_col, min_universe_size=min_universe_size), feature_name=feature_col, target_name=target_col)
        for regime, rows in buckets.items()
    }
