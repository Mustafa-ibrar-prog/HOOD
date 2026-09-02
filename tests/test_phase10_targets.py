"""Phase 10, Part 5 & 28: new forward-looking target tests
(src/research/phase10_targets.py). Confirms None-for-incomplete-window,
hand-computed correctness, and the structural no-live-import guarantee
already established for src/research/volatility_targets.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.data.bar import Bar
from src.research.phase10_targets import (
    future_absolute_return,
    future_max_drawdown,
    future_risk_adjusted_return,
    future_volatility_change,
    future_volatility_direction,
)
from src.research.targets import future_return
from src.research.volatility_targets import future_realized_volatility


def _bars(closes: list[float]) -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=c, high=c + 0.5, low=c - 0.5, close=c, volume=1000) for i, c in enumerate(closes)]


def test_future_absolute_return_is_mean_absolute_daily_return():
    closes = [100, 102, 101, 105, 104, 108]
    bars = _bars(closes)
    result = future_absolute_return(bars, horizon=3)
    # index 0: daily returns at i=1,2,3 -> (102-100)/100, (101-102)/102, (105-101)/101
    r1 = (102 - 100) / 100
    r2 = (101 - 102) / 102
    r3 = (105 - 101) / 101
    expected = (abs(r1) + abs(r2) + abs(r3)) / 3
    assert result[0] is not None and abs(result[0] - expected) < 1e-9


def test_future_absolute_return_none_when_window_incomplete():
    bars = _bars([100, 101, 102, 103])
    result = future_absolute_return(bars, horizon=3)
    assert result[-1] is None
    assert result[-2] is None


def test_future_absolute_return_differs_from_cumulative_on_round_trip():
    """A round-trip (up then back down to the same price) has near-zero
    NET cumulative move but a large AVERAGE absolute daily move — the
    entire reason these are tracked as separate targets."""
    from src.research.volatility_targets import future_absolute_cumulative_return

    closes = [100, 120, 100]
    bars = _bars(closes)
    cumulative = future_absolute_cumulative_return(bars, horizon=2)
    avg_abs = future_absolute_return(bars, horizon=2)
    assert cumulative[0] is not None and avg_abs[0] is not None
    assert cumulative[0] < 0.01  # net move ~0
    assert avg_abs[0] > 0.15  # both daily legs were large


def test_future_max_drawdown_zero_when_price_only_rises():
    bars = _bars([100, 101, 102, 103, 104, 105])
    dd = future_max_drawdown(bars, horizon=4)
    assert dd[0] == 0.0


def test_future_max_drawdown_detects_the_known_decline():
    closes = [100, 110, 90, 95, 100]
    bars = _bars(closes)
    dd = future_max_drawdown(bars, horizon=4)
    # path from i=0: [100,110,90,95,100]; peak=110 at step1, trough=90 at step2 -> dd = (90-110)/110
    expected = abs((90 - 110) / 110)
    assert dd[0] is not None and abs(dd[0] - expected) < 1e-9


def test_future_max_drawdown_is_non_negative():
    bars = _bars([100 + (i % 7) * 2 - 6 for i in range(40)])
    dd = future_max_drawdown(bars, horizon=10)
    for v in dd:
        if v is not None:
            assert v >= 0.0


def test_future_max_drawdown_none_when_window_incomplete():
    bars = _bars([100, 101, 102])
    dd = future_max_drawdown(bars, horizon=5)
    assert all(v is None for v in dd)


def test_future_risk_adjusted_return_matches_ratio_of_reused_targets():
    bars = _bars([100 + (i % 5) * 3 - 6 for i in range(60)])
    ret = future_return(bars, horizon=5)
    vol = future_realized_volatility(bars, horizon=5)
    rar = future_risk_adjusted_return(bars, horizon=5)
    for r, v, x in zip(ret, vol, rar):
        if r is None or v is None or v == 0:
            assert x is None
        else:
            assert x is not None and abs(x - r / v) < 1e-9


def test_future_volatility_change_and_direction_are_consistent():
    bars = _bars([100 + (i % 5) * 3 - 6 for i in range(80)])
    change = future_volatility_change(bars, horizon=5, vol_window=20)
    direction = future_volatility_direction(bars, horizon=5, vol_window=20)
    for c, d in zip(change, direction):
        if c is None:
            assert d is None
        elif c > 0:
            assert d == 1.0
        elif c < 0:
            assert d == -1.0
        else:
            assert d == 0.0


def test_future_volatility_change_none_when_horizon_or_baseline_unavailable():
    bars = _bars([100, 101, 102])
    change = future_volatility_change(bars, horizon=5, vol_window=20)
    assert all(v is None for v in change)


def test_future_volatility_change_is_sqrt_horizon_normalized_not_a_raw_subtraction():
    """future_realized_volatility(horizon) is sqrt(SUM of `horizon`
    squared daily returns), so under roughly CONSTANT daily volatility it
    grows ~sqrt(horizon) even with no real change in volatility. Without
    dividing back by sqrt(horizon) before comparing to the per-day
    realized_vol(vol_window) baseline, future_volatility_change would be
    spuriously large and positive at big horizons purely from this units
    mismatch — this test proves the fix holds: change should stay near 0
    (not grow with horizon) for a roughly constant-volatility series."""
    import math
    from datetime import datetime, timedelta, timezone

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    price = 100.0
    for i in range(120):
        price += 1.0 if i % 2 == 0 else -1.0  # constant-magnitude daily moves
        bars.append(Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=price, high=price + 0.1, low=price - 0.1, close=price, volume=1000))

    for horizon in (1, 5, 20):
        change = future_volatility_change(bars, horizon=horizon, vol_window=20)
        mid_region = [v for v in change[40:70] if v is not None]
        assert mid_region, f"no defined values for horizon={horizon}"
        # under near-constant volatility, the sqrt(horizon)-normalized change should be small in
        # magnitude relative to the (unnormalized) raw target level, regardless of horizon
        assert all(abs(v) < 0.02 for v in mid_region), f"horizon={horizon} change not small: {mid_region}"


def test_future_volatility_change_without_normalization_would_grow_with_horizon():
    """Sanity-checks the BUG this fix addresses: the naive (unnormalized)
    difference future_realized_volatility(h) - realized_vol(20) DOES grow
    with horizon under constant volatility, confirming the sqrt(h)
    division above is load-bearing, not cosmetic."""
    from datetime import datetime, timedelta, timezone

    from src.features.volatility import RealizedVolatility
    from src.research.volatility_targets import future_realized_volatility

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    price = 100.0
    for i in range(120):
        price += 1.0 if i % 2 == 0 else -1.0
        bars.append(Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=price, high=price + 0.1, low=price - 0.1, close=price, volume=1000))

    current_vol = RealizedVolatility(20).compute(bars)
    naive_deltas_by_horizon = {}
    for horizon in (1, 20):
        future_vol = future_realized_volatility(bars, horizon)
        naive = [f - c for f, c in zip(future_vol, current_vol) if f is not None and c is not None]
        naive_deltas_by_horizon[horizon] = sum(naive[40:70]) / len(naive[40:70])
    assert naive_deltas_by_horizon[20] > naive_deltas_by_horizon[1] * 2  # confirms the raw (buggy) version scales with horizon


def test_phase10_targets_module_never_imported_by_live_path():
    import ast
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    forbidden = ("src.strategy", "src.position_manager", "src.orchestrator", "src.execution")
    for path in [repo_root / "src" / "strategy", repo_root / "src" / "position_manager", repo_root / "src" / "orchestrator.py", repo_root / "src" / "execution"]:
        files = [path] if path.is_file() else (list(path.rglob("*.py")) if path.is_dir() else [])
        for f in files:
            tree = ast.parse(f.read_text(), filename=str(f))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert "phase10_targets" not in node.module, f"{f} imports phase10_targets"
                    assert "volatility_persistence" not in node.module, f"{f} imports volatility_persistence"
