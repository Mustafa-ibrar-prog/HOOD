"""Phase 22, Part 7 — REALIZED_OPTION_PRICE_VOLATILITY_PROXY (never IV):
close-to-close vol, mean-abs-return, Parkinson vol, true-range proxy,
volatility ratio, and range-expansion ratio, all causal and index-
aligned."""

from __future__ import annotations

import pytest

from src.options.price_volatility_proxy import (
    close_to_close_volatility,
    mean_abs_return,
    parkinson_volatility,
    range_expansion_ratio,
    trailing_return,
    true_range_proxy,
    volatility_ratio,
)


def test_trailing_return_none_before_lookback():
    closes = [10, 11, 12, 13, 14]
    out = trailing_return(closes, 3)
    assert out[0] is None and out[1] is None and out[2] is None
    assert out[3] == pytest.approx((13 - 10) / 10)
    assert out[4] == pytest.approx((14 - 11) / 11)


def test_trailing_return_rejects_bad_lookback():
    with pytest.raises(ValueError):
        trailing_return([1.0, 2.0], 0)


def test_trailing_return_none_on_zero_base():
    closes = [0.0, 5.0, 6.0]
    out = trailing_return(closes, 1)
    assert out[1] is None  # base close was 0


def test_close_to_close_volatility_none_before_window():
    closes = [10, 10.1, 9.9, 10.2, 10.0, 10.3]
    out = close_to_close_volatility(closes, 3)
    assert out[0] is None and out[1] is None and out[2] is None
    assert out[3] is not None
    assert out[3] >= 0


def test_close_to_close_volatility_zero_for_constant_returns():
    closes = [10, 11, 12.1, 13.31, 14.641]  # constant 10% return each step
    out = close_to_close_volatility(closes, 3)
    assert out[-1] == pytest.approx(0.0, abs=1e-9)


def test_close_to_close_volatility_rejects_small_window():
    with pytest.raises(ValueError):
        close_to_close_volatility([1.0, 2.0], 1)


def test_mean_abs_return_matches_hand_computation():
    closes = [10, 11, 10, 11]  # returns: None, +10%, -9.09%, +10%
    out = mean_abs_return(closes, 2)
    # window ending at i=2: returns[1],[2] = 0.1, -0.0909...
    expected = (0.1 + abs((10 - 11) / 11)) / 2
    assert out[2] == pytest.approx(expected)


def test_parkinson_volatility_positive_and_none_before_window():
    highs = [11, 12, 11.5, 13, 12.5]
    lows = [9, 10, 9.5, 11, 10.5]
    out = parkinson_volatility(highs, lows, 3)
    assert out[0] is None and out[1] is None
    assert out[2] is not None and out[2] > 0


def test_parkinson_volatility_none_on_bad_high_low():
    highs = [11, 12, 0]
    lows = [9, 10, 5]
    out = parkinson_volatility(highs, lows, 2)
    assert out[2] is None  # a high of 0 makes the log undefined


def test_true_range_proxy_none_at_index_zero():
    highs = [11, 12, 13, 12.5]
    lows = [9, 10, 11, 10.5]
    closes = [10, 11, 12, 11.5]
    out = true_range_proxy(highs, lows, closes, 2)
    assert out[0] is None  # no prior close
    assert out[1] is None  # window of 2 not yet available (needs index >= window)


def test_true_range_proxy_positive_once_available():
    highs = [11, 12, 13, 12.5, 13.5]
    lows = [9, 10, 11, 10.5, 11.5]
    closes = [10, 11, 12, 11.5, 12.5]
    out = true_range_proxy(highs, lows, closes, 2)
    assert out[2] is not None and out[2] > 0


def test_volatility_ratio_elementwise():
    short = [0.02, None, 0.04]
    long_ = [0.01, 0.02, 0.0]
    out = volatility_ratio(short, long_)
    assert out[0] == pytest.approx(2.0)
    assert out[1] is None  # short is None
    assert out[2] is None  # long is 0


def test_volatility_ratio_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        volatility_ratio([1.0], [1.0, 2.0])


def test_range_expansion_ratio_none_before_window():
    highs = [11, 12, 13, 14]
    lows = [9, 10, 11, 12]
    closes = [10, 11, 12, 13]
    out = range_expansion_ratio(highs, lows, closes, 3)
    assert out[0] is None and out[1] is None and out[2] is None


def test_range_expansion_ratio_one_for_constant_range():
    # constant (H-L)/C ratio every day -> today's ratio equals the baseline exactly -> 1.0
    highs = [11, 11, 11, 11, 11]
    lows = [9, 9, 9, 9, 9]
    closes = [10, 10, 10, 10, 10]
    out = range_expansion_ratio(highs, lows, closes, 3)
    assert out[3] == pytest.approx(1.0)


def test_range_expansion_ratio_above_one_for_a_wide_day():
    highs = [11, 11, 11, 20]  # last day has a much wider range
    lows = [9, 9, 9, 5]
    closes = [10, 10, 10, 10]
    out = range_expansion_ratio(highs, lows, closes, 3)
    assert out[3] > 1.0
