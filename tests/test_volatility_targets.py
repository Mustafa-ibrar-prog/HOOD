"""Phase 9, Part 2 & 21: volatility/magnitude target construction tests —
correctness against hand-computed examples, and a no-future-leakage proof
(targets DO look ahead by design; the proof here is that they look ahead
by EXACTLY the declared horizon, never further, and are None once the
future data needed doesn't exist)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from src.data.bar import Bar
from src.research.volatility_targets import (
    future_absolute_cumulative_return,
    future_max_absolute_move,
    future_realized_variance,
    future_realized_volatility,
)

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _bars_from_closes(closes: list[float]) -> list[Bar]:
    return [Bar(timestamp=T0 + timedelta(days=i), symbol="AAPL", timeframe="day", open=c, high=c + 1, low=c - 1, close=c, volume=1000) for i, c in enumerate(closes)]


def test_realized_variance_matches_hand_computed_example():
    # closes: 100, 101, 99, 102 -> daily returns: None, 0.01, -0.0198.., 0.0303..
    closes = [100.0, 101.0, 99.0, 102.0]
    bars = _bars_from_closes(closes)
    variance = future_realized_variance(bars, horizon=2)
    r1 = (101 - 100) / 100
    r2 = (99 - 101) / 101
    r3 = (102 - 99) / 99
    expected_i0 = r1 ** 2 + r2 ** 2  # index 0's horizon=2 window is returns at index 1,2
    assert variance[0] is not None and abs(variance[0] - expected_i0) < 1e-9
    expected_i1 = r2 ** 2 + r3 ** 2
    assert variance[1] is not None and abs(variance[1] - expected_i1) < 1e-9


def test_realized_volatility_is_sqrt_of_variance():
    closes = [100.0 + i * 0.5 for i in range(20)]
    bars = _bars_from_closes(closes)
    variance = future_realized_variance(bars, horizon=5)
    vol = future_realized_volatility(bars, horizon=5)
    for v, vol_v in zip(variance, vol):
        if v is not None:
            assert vol_v is not None and abs(vol_v - v ** 0.5) < 1e-9
        else:
            assert vol_v is None


def test_none_for_indices_without_a_full_forward_window():
    closes = [100.0 + i for i in range(10)]
    bars = _bars_from_closes(closes)
    variance = future_realized_variance(bars, horizon=5)
    # the last 5 indices cannot have a full 5-bar-ahead window
    assert all(v is None for v in variance[-5:])
    assert variance[4] is not None  # index 4 has bars 5..9 available (5 more bars)


def test_absolute_cumulative_return_matches_hand_computed_example():
    closes = [100.0, 110.0, 90.0]
    bars = _bars_from_closes(closes)
    result = future_absolute_cumulative_return(bars, horizon=2)
    expected = abs((90.0 - 100.0) / 100.0)
    assert result[0] is not None and abs(result[0] - expected) < 1e-9


def test_absolute_cumulative_return_can_differ_from_realized_variance_direction():
    """A round-trip (up then back down to the start) has LOW absolute
    cumulative return but HIGH realized variance — the whole reason both
    targets are preregistered separately."""
    closes = [100.0, 150.0, 100.0]  # +50% then -33.3% -> net ~0% cumulative, but large squared daily moves
    bars = _bars_from_closes(closes)
    abs_cum = future_absolute_cumulative_return(bars, horizon=2)[0]
    variance = future_realized_variance(bars, horizon=2)[0]
    assert abs_cum is not None and abs_cum < 0.01  # net round-trip ~0
    assert variance is not None and variance > 0.1  # but real variance is large


def test_max_absolute_move_finds_the_single_largest_day():
    closes = [100.0, 101.0, 130.0, 129.0, 128.0]  # a big jump at day 2
    bars = _bars_from_closes(closes)
    result = future_max_absolute_move(bars, horizon=3)
    r1 = (101 - 100) / 100
    r2 = (130 - 101) / 101
    r3 = (129 - 130) / 130
    expected = max(abs(r1), abs(r2), abs(r3))
    assert result[0] is not None and abs(result[0] - expected) < 1e-9


def test_max_absolute_move_never_exceeds_realized_volatility_scale_for_a_single_spike():
    """Sanity relationship: with only ONE non-trivial move in the window,
    max_absolute_move and sqrt(realized_variance) should be close (both
    dominated by the same single large move)."""
    closes = [100.0, 100.1, 100.05, 150.0, 100.1]
    bars = _bars_from_closes(closes)
    max_move = future_max_absolute_move(bars, horizon=4)[0]
    vol = future_realized_volatility(bars, horizon=4)[0]
    assert max_move is not None and vol is not None
    assert max_move <= vol + 1e-9  # max single-day move can't exceed the aggregate sqrt-sum-of-squares


def test_horizon_must_be_positive():
    import pytest

    bars = _bars_from_closes([100.0, 101.0, 102.0])
    for fn in (future_realized_variance, future_realized_volatility, future_absolute_cumulative_return, future_max_absolute_move):
        with pytest.raises(ValueError):
            fn(bars, horizon=0)


def test_targets_are_never_imported_by_the_live_trading_path():
    """Structural check mirroring src.research.targets' own module
    docstring guarantee — grep the live-path modules for any import of
    this module."""
    import ast
    from pathlib import Path

    live_modules = list((Path(__file__).resolve().parent.parent / "src" / "strategy").glob("*.py")) + \
        list((Path(__file__).resolve().parent.parent / "src" / "position_manager").glob("*.py")) + \
        [Path(__file__).resolve().parent.parent / "src" / "orchestrator.py"]
    for path in live_modules:
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "volatility_targets" not in node.module, f"{path} imports volatility_targets — the live path must never see forward-looking targets"
