"""Tests for causal regime labeling and per-regime performance breakdown
(Phase 4, section 12)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.backtesting.journal import BacktestTrade
from src.data.bar import Bar
from src.research.regime import bucket_trades_by_regime, label_bars_by_regime, regime_performance_report


def _bars(closes: list[float]) -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol="TEST", timeframe="day", open=c, high=c + 1, low=c - 1, close=c, volume=1000)
        for i, c in enumerate(closes)
    ]


def _trade(entry_ts, net_pnl: float) -> BacktestTrade:
    return BacktestTrade(
        trade_id="T", backtest_id="B", strategy="s", symbol="TEST", entry_timestamp=entry_ts, entry_price=100.0,
        exit_timestamp=entry_ts + timedelta(days=1), exit_price=101.0, quantity=1, gross_pnl=net_pnl, fees=0.0,
        slippage=0.0, net_pnl=net_pnl, holding_period_minutes=1440.0, entry_reason="", exit_reason="", risk_decision="APPROVED",
    )


def test_label_bars_by_regime_is_unknown_before_enough_history():
    bars = _bars([100.0] * 10)
    labels = label_bars_by_regime(bars, fast_window=5, slow_window=20, vol_window=5, vol_lookback=20)
    assert labels[bars[0].timestamp] == "unknown"


def test_label_bars_by_regime_detects_bull_trend():
    closes = [100.0 + i for i in range(120)]
    bars = _bars(closes)
    labels = label_bars_by_regime(bars, fast_window=5, slow_window=20, vol_window=10, vol_lookback=50)
    assert labels[bars[-1].timestamp].startswith("bull_")


def test_label_bars_by_regime_detects_bear_trend():
    closes = [200.0 - i for i in range(120)]
    bars = _bars(closes)
    labels = label_bars_by_regime(bars, fast_window=5, slow_window=20, vol_window=10, vol_lookback=50)
    assert labels[bars[-1].timestamp].startswith("bear_")


def test_bucket_trades_by_regime_uses_entry_timestamp():
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2024, 1, 2, tzinfo=timezone.utc)
    trades = [_trade(t0, 10.0), _trade(t1, -5.0)]
    regime_by_ts = {t0: "bull_low_vol", t1: "bear_high_vol"}
    buckets = bucket_trades_by_regime(trades, regime_by_ts)
    assert len(buckets["bull_low_vol"]) == 1
    assert len(buckets["bear_high_vol"]) == 1


def test_bucket_trades_by_regime_falls_back_to_unknown():
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    trades = [_trade(t0, 10.0)]
    buckets = bucket_trades_by_regime(trades, {})
    assert "unknown" in buckets


def test_regime_performance_report_computes_per_regime_stats():
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    buckets = {"bull_low_vol": [_trade(t0, 10.0), _trade(t0, 20.0)], "bear_high_vol": [_trade(t0, -15.0)]}
    report = regime_performance_report(buckets, starting_cash=10_000.0)
    assert report["bull_low_vol"].trades.trade_count == 2
    assert report["bull_low_vol"].trades.win_rate == 1.0
    assert report["bear_high_vol"].trades.trade_count == 1
    assert report["bear_high_vol"].trades.win_rate == 0.0
