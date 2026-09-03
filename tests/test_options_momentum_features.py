"""Phase 22, Part 4 (Theme C) — the option contract's own price
momentum/acceleration/gap/trend-persistence/range-expansion features."""

from __future__ import annotations

from datetime import date

import pytest

from src.options.momentum_features import (
    option_gap,
    option_range_expansion,
    option_return_acceleration,
    trailing_option_return,
    trend_persistence,
)
from src.options.price_history import OptionPriceBar


def _bars(closes, opens=None, highs=None, lows=None):
    n = len(closes)
    opens = opens or closes
    highs = highs or [c + 0.5 for c in closes]
    lows = lows or [c - 0.5 for c in closes]
    return [OptionPriceBar(date=date(2022, 1, i + 1), open=opens[i], high=highs[i], low=lows[i], close=closes[i]) for i in range(n)]


def test_trailing_option_return_matches_generic_trailing_return():
    bars = _bars([10, 11, 12, 13, 14, 15])
    out = trailing_option_return(bars, 2)
    assert out[0] is None and out[1] is None
    assert out[2] == pytest.approx((12 - 10) / 10)


def test_option_return_acceleration_none_for_first_two_bars():
    bars = _bars([10, 11, 12.1, 13])
    out = option_return_acceleration(bars)
    assert out[0] is None and out[1] is None
    # daily returns: None, 0.1, 0.1, ~0.0744 -> acceleration[2] = 0.1-0.1=0, acceleration[3]=0.0744-0.1
    assert out[2] == pytest.approx(0.0, abs=1e-9)


def test_option_gap_uses_open_vs_prior_close():
    bars = _bars(closes=[10, 11], opens=[10, 10.5])
    out = option_gap(bars)
    assert out[0] is None
    assert out[1] == pytest.approx((10.5 - 10) / 10)


def test_option_gap_none_on_zero_prior_close():
    bars = _bars(closes=[0.0, 1.0], highs=[0.0, 1.5], lows=[0.0, 0.5])
    out = option_gap(bars)
    assert out[1] is None


def test_trend_persistence_all_up_days_is_one():
    bars = _bars([10, 11, 12, 13, 14])  # every day is an up-day
    out = trend_persistence(bars, 3)
    assert out[0] is None and out[1] is None and out[2] is None
    assert out[3] == pytest.approx(1.0)
    assert out[4] == pytest.approx(1.0)


def test_trend_persistence_mixed_up_down():
    bars = _bars([10, 11, 10, 11, 10])  # alternating up/down
    out = trend_persistence(bars, 2)
    # daily returns starting idx1: +10%, -9.09%, +10%, -9.09%
    assert out[2] == pytest.approx(0.5)  # 1 up out of 2 (idx1 up, idx2 down)


def test_trend_persistence_rejects_bad_window():
    with pytest.raises(ValueError):
        trend_persistence(_bars([10, 11]), 0)


def test_option_range_expansion_matches_generic_ratio():
    bars = _bars([10, 10, 10, 10], highs=[11, 11, 11, 20], lows=[9, 9, 9, 5])
    out = option_range_expansion(bars, 3)
    assert out[3] > 1.0  # last day's range is much wider than the trailing baseline
