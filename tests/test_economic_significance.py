"""Phase 7, Part 6 & 19: economic significance tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.backtesting.journal import BacktestTrade
from src.backtesting.metrics import compute_performance_metrics
from src.research.economic_significance import compute_capacity_proxy, cost_multiplier_edge, evaluate_economic_significance

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _trade(pnl, fees=1.0, slippage=0.5, price=100.0, qty=10):
    gross = pnl + fees  # net_pnl = gross_pnl - fees (this engine's real convention)
    return BacktestTrade(
        trade_id="T", backtest_id="B", strategy="s", symbol="AAPL", entry_timestamp=T0, entry_price=price,
        exit_timestamp=T0 + timedelta(days=5), exit_price=price + 1, quantity=qty, gross_pnl=gross, fees=fees,
        slippage=slippage, net_pnl=pnl, holding_period_minutes=7200.0, entry_reason="", exit_reason="", risk_decision="APPROVED",
    )


def test_evaluate_economic_significance_basic_fields():
    trades = [_trade(10.0), _trade(-5.0), _trade(20.0)]
    metrics = compute_performance_metrics(equity_curve=[], trades=trades, starting_cash=10_000.0)
    report = evaluate_economic_significance(trades=trades, metrics=metrics, span_years=1.0)
    assert report.trade_count == 3
    assert report.net_expectancy == sum(t.net_pnl for t in trades) / 3
    assert report.total_fees == sum(t.fees for t in trades)
    assert report.trade_frequency_per_year == 3.0


def test_evaluate_economic_significance_empty_trades():
    metrics = compute_performance_metrics(equity_curve=[], trades=[], starting_cash=10_000.0)
    report = evaluate_economic_significance(trades=[], metrics=metrics, span_years=1.0)
    assert report.trade_count == 0
    assert report.gross_expectancy == 0.0
    assert report.capacity_proxy_usd is None


def test_payoff_ratio_matches_avg_win_over_avg_loss():
    trades = [_trade(10.0), _trade(-5.0)]
    metrics = compute_performance_metrics(equity_curve=[], trades=trades, starting_cash=10_000.0)
    report = evaluate_economic_significance(trades=trades, metrics=metrics)
    assert abs(report.payoff_ratio - (10.0 / 5.0)) < 1e-9


def test_capacity_proxy_is_the_binding_smallest_trade():
    trades = [_trade(1.0, price=100.0, qty=10), _trade(1.0, price=1000.0, qty=1)]  # notional: 1000 vs 1000 -> same
    proxy = compute_capacity_proxy(trades, participation_rate=0.01)
    assert proxy == 1000.0 / 0.01


def test_capacity_proxy_none_for_no_trades():
    assert compute_capacity_proxy([], participation_rate=0.01) is None


# --- cost multiplier edge (1x/2x/3x costs) -------------------------------------------------


def test_cost_multiplier_edge_scales_fees_only_not_slippage():
    """net_pnl = gross_pnl - fees (this engine's convention — slippage is
    already baked into gross_pnl via the fill price, see
    src/backtesting/engine.py). Scaling fees by 2x should change net_pnl
    by exactly the extra fee amount."""
    t = _trade(10.0, fees=2.0)
    report = cost_multiplier_edge([t], multipliers=(1.0, 2.0, 3.0))
    base = next(p for p in report.points if p.cost_multiplier == 1.0)
    doubled = next(p for p in report.points if p.cost_multiplier == 2.0)
    assert abs(base.net_pnl_total - t.net_pnl) < 1e-9
    assert abs((base.net_pnl_total - doubled.net_pnl_total) - t.fees) < 1e-9


def test_cost_multiplier_edge_survives_flag():
    profitable = _trade(100.0, fees=2.0)  # gross_pnl = 102; at 100x fees, 102 - 200 < 0
    report = cost_multiplier_edge([profitable], multipliers=(1.0, 100.0))
    assert report.points[0].edge_survives is True
    assert report.points[1].edge_survives is False
