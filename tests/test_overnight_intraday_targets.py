"""Phase 13, Part 6, 28: forward-looking overnight/intraday target tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.bar import Bar
from src.research.overnight_intraday_targets import future_intraday_return, future_overnight_return


def _bars(ohlc: list[tuple[float, float]]) -> list[Bar]:
    """ohlc: list of (open, close) pairs, one per bar."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i, (o, c) in enumerate(ohlc):
        high, low = max(o, c) + 1, min(o, c) - 1
        bars.append(Bar(timestamp=start + timedelta(days=i), symbol="X", timeframe="day", open=o, high=high, low=low, close=c, volume=1000))
    return bars


def test_future_overnight_return_horizon_1_hand_computed():
    # bar0: (100,100); bar1: (105,110) -> overnight_1 = 105/100-1=0.05
    bars = _bars([(100, 100), (105, 110), (108, 112)])
    result = future_overnight_return(bars, horizon=1)
    assert result[0] is not None and abs(result[0] - 0.05) < 1e-12
    # bar1->bar2 overnight = 108/110-1
    assert result[1] is not None and abs(result[1] - (108 / 110 - 1)) < 1e-12
    assert result[2] is None  # no bar3


def test_future_overnight_return_horizon_5_is_cumulative_sum():
    ohlc = [(100 + i, 100 + i + 0.5) for i in range(10)]
    bars = _bars(ohlc)
    result = future_overnight_return(bars, horizon=5)
    # hand-compute at i=0: sum of overnight[1..5]
    expected = 0.0
    closes = [c for _o, c in ohlc]
    opens = [o for o, _c in ohlc]
    for j in range(1, 6):
        expected += opens[j] / closes[j - 1] - 1
    assert result[0] is not None and abs(result[0] - expected) < 1e-9


def test_future_intraday_return_horizon_1_hand_computed():
    bars = _bars([(100, 100), (105, 110), (108, 112)])
    result = future_intraday_return(bars, horizon=1)
    # target[0] = intraday at bar1 = 110/105-1
    assert result[0] is not None and abs(result[0] - (110 / 105 - 1)) < 1e-12
    assert result[1] is not None and abs(result[1] - (112 / 108 - 1)) < 1e-12
    assert result[2] is None


def test_future_intraday_return_horizon_5_cumulative():
    ohlc = [(100 + i, 100 + i + 0.5) for i in range(10)]
    bars = _bars(ohlc)
    result = future_intraday_return(bars, horizon=5)
    expected = sum((c / o - 1) for o, c in ohlc[1:6])
    assert result[0] is not None and abs(result[0] - expected) < 1e-9


def test_none_when_window_incomplete():
    bars = _bars([(100, 101), (102, 103)])
    assert all(v is None for v in future_overnight_return(bars, horizon=5))
    assert all(v is None for v in future_intraday_return(bars, horizon=5))


def test_none_on_non_positive_price():
    bars = _bars([(100, 100), (0, 50), (105, 110)])  # bar1 has open=0
    result = future_overnight_return(bars, horizon=1)
    assert result[0] is None  # target[0] needs overnight[1] which is undefined (open=0)


def test_invalid_horizon_rejected():
    bars = _bars([(100, 101), (102, 103)])
    with pytest.raises(ValueError):
        future_overnight_return(bars, horizon=0)
    with pytest.raises(ValueError):
        future_intraday_return(bars, horizon=-1)
