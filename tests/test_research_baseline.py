"""Tests for baseline comparisons (Phase 4, section 18)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.bar import Bar
from src.research.baseline import buy_and_hold_curve, no_trade_curve, random_entry_baseline

UTC = timezone.utc


def _bars(closes: list[float]) -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol="TEST", timeframe="day", open=c, high=c + 1, low=c - 1, close=c, volume=1000)
        for i, c in enumerate(closes)
    ]


def test_buy_and_hold_tracks_price_appreciation():
    bars = _bars([100.0, 110.0, 120.0])
    curve = buy_and_hold_curve(bars, starting_cash=10_000.0)
    assert len(curve) == 3
    # 100 shares bought at $100 open; final equity should track the ~20% gain closely
    assert curve[-1].equity > curve[0].equity
    assert curve[-1].equity == pytest.approx(10_000.0 * 1.20, rel=0.02)


def test_buy_and_hold_empty_bars_is_safe():
    assert buy_and_hold_curve([], starting_cash=10_000.0) == []


def test_no_trade_curve_never_changes_equity():
    bars = _bars([100.0, 200.0, 50.0])  # even wild price moves...
    curve = no_trade_curve(bars, starting_cash=10_000.0)
    assert all(p.equity == 10_000.0 for p in curve)  # ...never move an all-cash portfolio


def test_random_entry_baseline_is_deterministic_given_a_seed():
    bars = _bars([100.0 + i for i in range(50)])
    trades_a = random_entry_baseline(bars, quantity=10, holding_period_bars=5, n_trades=10, seed=42)
    trades_b = random_entry_baseline(bars, quantity=10, holding_period_bars=5, n_trades=10, seed=42)
    assert trades_a == trades_b


def test_random_entry_baseline_different_seeds_differ():
    bars = _bars([100.0 + i for i in range(50)])
    trades_a = random_entry_baseline(bars, quantity=10, holding_period_bars=5, n_trades=10, seed=1)
    trades_b = random_entry_baseline(bars, quantity=10, holding_period_bars=5, n_trades=10, seed=2)
    assert trades_a != trades_b


def test_random_entry_baseline_respects_holding_period():
    bars = _bars([100.0 + i for i in range(50)])
    trades = random_entry_baseline(bars, quantity=10, holding_period_bars=7, n_trades=5, seed=1)
    for t in trades:
        assert t.exit_index - t.entry_index == 7


def test_random_entry_baseline_empty_when_series_too_short():
    bars = _bars([100.0, 101.0])
    trades = random_entry_baseline(bars, quantity=10, holding_period_bars=10, n_trades=5, seed=1)
    assert trades == []
