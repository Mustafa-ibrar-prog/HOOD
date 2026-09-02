"""Phase 11, Parts 14-15, 28: tail-risk and drawdown-recovery tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.backtesting.portfolio import EquityPoint
from src.research.tail_risk import compute_tail_risk, recovery_time_bars


def test_worst_1day_return_is_the_minimum():
    report = compute_tail_risk([0.01, -0.05, 0.02, -0.10, 0.03])
    assert report.worst_1day_return == -0.10


def test_worst_5day_return_uses_rolling_overlapping_windows():
    # 5 identical -1% days -> 5-day cumulative = (0.99)^5 - 1
    returns = [-0.01] * 5
    report = compute_tail_risk(returns)
    expected = (0.99 ** 5) - 1
    assert report.worst_5day_return is not None and abs(report.worst_5day_return - expected) < 1e-9


def test_var_95_is_the_5th_percentile_hand_computed():
    returns = [float(x) for x in range(1, 21)]  # sorted 1..20, n=20
    report = compute_tail_risk(returns)
    # nearest-rank percentile: index = round(0.05 * (20-1)) = round(0.95) = 1 (0-indexed) -> sorted[1] = 2.0
    assert report.var_95 == 2.0


def test_cvar_is_worse_than_or_equal_to_var():
    returns = [0.01, 0.02, -0.01, -0.02, -0.15, -0.20, 0.03, -0.01, 0.0, 0.01] * 3
    report = compute_tail_risk(returns)
    assert report.cvar_95 is not None and report.var_95 is not None
    assert report.cvar_95 <= report.var_95  # CVaR is the mean of the tail AT OR BEYOND VaR -> at least as bad


def test_var99_none_below_20_observations():
    report = compute_tail_risk([0.01, -0.01, 0.02])
    assert report.var_99 is None
    assert "VaR99" in report.sample_size_caveat


def test_empty_series_handled_gracefully():
    report = compute_tail_risk([])
    assert report.n_observations == 0
    assert report.worst_1day_return is None


def _equity_curve(equities: list[float]) -> list[EquityPoint]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    points = []
    peak = equities[0]
    for i, eq in enumerate(equities):
        peak = max(peak, eq)
        dd = eq - peak
        dd_pct = dd / peak if peak > 0 else 0.0
        points.append(EquityPoint(timestamp=start + timedelta(days=i), equity=eq, cash=eq, positions_value=0.0, gross_exposure=0.0, net_exposure=0.0, drawdown=dd, drawdown_pct=dd_pct))
    return points


def test_recovery_time_hand_computed():
    # peak 100 -> trough 80 (day 2) -> recovers to 100 at day 5 -> recovery = 3 bars from trough
    curve = _equity_curve([100, 95, 80, 85, 92, 100, 105])
    assert recovery_time_bars(curve) == 3


def test_recovery_time_none_when_never_recovered():
    curve = _equity_curve([100, 90, 80, 85, 88])
    assert recovery_time_bars(curve) is None


def test_recovery_time_none_when_no_drawdown_ever_occurred():
    curve = _equity_curve([100, 101, 102, 103])
    assert recovery_time_bars(curve) is None


def test_recovery_time_empty_curve():
    assert recovery_time_bars([]) is None
