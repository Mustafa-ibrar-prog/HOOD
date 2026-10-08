from __future__ import annotations

import pytest

from src.market.indicators import (
    bid_ask_spread_pct,
    detect_breakdown_continuation,
    detect_breakout_continuation,
    detect_failed_breakdown,
    detect_failed_breakout,
    detect_reversal,
    ema,
    higher_highs_lower_highs,
    is_liquid,
    macd,
    rsi,
    vwap,
)
from tests.conftest import make_bars


def test_ema_first_value_equals_first_input():
    result = ema([10.0, 11.0, 12.0], period=3)
    assert result[0] == 10.0
    assert len(result) == 3


def test_ema_tracks_rising_series_upward():
    result = ema([1.0, 2.0, 3.0, 4.0, 5.0], period=3)
    assert result[-1] > result[0]
    assert result == sorted(result)  # monotonically increasing for a monotonic input


def test_ema_empty_input_returns_empty():
    assert ema([], period=5) == []


def test_rsi_all_gains_approaches_100():
    values = [float(i) for i in range(1, 30)]  # strictly increasing
    result = rsi(values, period=14)
    assert result[-1] > 95


def test_rsi_all_losses_approaches_0():
    values = [float(i) for i in range(30, 1, -1)]  # strictly decreasing
    result = rsi(values, period=14)
    assert result[-1] < 5


def test_rsi_flat_series_is_neutral():
    values = [100.0] * 20
    result = rsi(values, period=14)
    assert 45 <= result[-1] <= 55


def test_rsi_bounded_0_to_100():
    values = [10, 12, 9, 15, 11, 20, 5, 30, 2, 40]
    result = rsi([float(v) for v in values], period=5)
    assert all(0 <= v <= 100 for v in result)


def test_macd_histogram_positive_on_accelerating_uptrend():
    values = [float(i) for i in range(1, 60)]
    macd_line, signal_line, histogram = macd(values, fast=12, slow=26, signal=9)
    assert histogram[-1] > 0


def test_macd_returns_equal_length_series():
    values = [float(i) for i in range(50)]
    macd_line, signal_line, histogram = macd(values)
    assert len(macd_line) == len(signal_line) == len(histogram) == len(values)


def test_vwap_weights_by_volume():
    bars = make_bars(closes=[100.0, 200.0], volumes=[1000, 1])
    # Heavily weighted toward the first bar's price
    result = vwap(bars)
    assert result is not None
    assert result < 110


def test_vwap_none_when_no_volume():
    bars = make_bars(closes=[100.0, 101.0], volumes=[0, 0])
    assert vwap(bars) is None


def test_higher_highs_detected_on_uptrend():
    bars = make_bars([100, 101, 102, 103, 104])
    higher, lower = higher_highs_lower_highs(bars, lookback=5)
    assert higher is True
    assert lower is False


def test_lower_highs_detected_on_downtrend():
    bars = make_bars([104, 103, 102, 101, 100])
    higher, lower = higher_highs_lower_highs(bars, lookback=5)
    assert lower is True
    assert higher is False


def test_no_clear_structure_on_choppy_series():
    bars = make_bars([100, 102, 99, 103, 98])
    higher, lower = higher_highs_lower_highs(bars, lookback=5)
    assert higher is False
    assert lower is False


def test_breakout_continuation_detected_after_holding_above_resistance():
    # 20 bars of consolidation around 100, then 2 confirming bars above it
    pre = [100.0 + (i % 3) * 0.1 for i in range(20)]
    confirm = [103.0, 104.0]
    bars = make_bars(pre + confirm)
    assert detect_breakout_continuation(bars, resistance_lookback=20, confirm_bars=2) is True


def test_no_breakout_continuation_without_enough_history():
    bars = make_bars([100.0, 101.0, 102.0])
    assert detect_breakout_continuation(bars, resistance_lookback=20, confirm_bars=2) is False


def test_failed_breakout_detected_when_price_falls_back_below_resistance():
    pre = [100.0] * 20
    spike_then_fail = [105.0, 98.0]  # spiked above resistance, then closed back below
    bars = make_bars(pre + spike_then_fail)
    assert detect_failed_breakout(bars, resistance_lookback=20) is True


def test_no_failed_breakout_when_never_broke_out():
    bars = make_bars([100.0] * 25)
    assert detect_failed_breakout(bars, resistance_lookback=20) is False


def test_bid_ask_spread_pct_normal_quote():
    assert abs(bid_ask_spread_pct(1.00, 1.10) - (0.10 / 1.05)) < 1e-9


def test_bid_ask_spread_pct_crossed_quote_is_infinite():
    assert bid_ask_spread_pct(1.10, 1.00) == float("inf")


def test_bid_ask_spread_pct_zero_bid_is_infinite():
    assert bid_ask_spread_pct(0.0, 1.00) == float("inf")


def test_is_liquid_true_when_above_minimums():
    assert is_liquid(volume=100, open_interest=200, min_volume=50, min_open_interest=100) is True


def test_is_liquid_false_when_missing_data():
    assert is_liquid(volume=None, open_interest=200, min_volume=50, min_open_interest=100) is False


def test_is_liquid_false_when_below_minimums():
    assert is_liquid(volume=10, open_interest=5, min_volume=50, min_open_interest=100) is False


# --- Downside mirrors: detect_breakdown_continuation / detect_failed_breakdown --

def test_breakdown_continuation_detected_after_holding_below_support():
    pre = [100.0 + (i % 3) * 0.1 for i in range(20)]
    confirm = [97.0, 96.0]
    bars = make_bars(pre + confirm)
    assert detect_breakdown_continuation(bars, support_lookback=20, confirm_bars=2) is True


def test_no_breakdown_continuation_without_enough_history():
    bars = make_bars([100.0, 99.0, 98.0])
    assert detect_breakdown_continuation(bars, support_lookback=20, confirm_bars=2) is False


def test_no_breakdown_continuation_when_price_stays_above_support():
    pre = [100.0] * 20
    still_above = [101.0, 102.0]
    bars = make_bars(pre + still_above)
    assert detect_breakdown_continuation(bars, support_lookback=20, confirm_bars=2) is False


def test_failed_breakdown_detected_when_price_recovers_back_above_support():
    pre = [100.0] * 20
    dip_then_recover = [95.0, 102.0]  # dipped below support, then closed back above
    bars = make_bars(pre + dip_then_recover)
    assert detect_failed_breakdown(bars, support_lookback=20) is True


def test_no_failed_breakdown_when_never_broke_down():
    bars = make_bars([100.0] * 25)
    assert detect_failed_breakdown(bars, support_lookback=20) is False


# --- detect_reversal: two-stage structure break -------------------------------

def test_reversal_detected_for_bullish_thesis_on_lower_high_and_lower_low():
    # Prior swing: a clean move up to ~110. Recent swing: fails to retest
    # that high AND breaks below the prior swing's own low.
    prior_swing = [100.0, 102.0, 104.0, 106.0, 108.0, 110.0, 109.0, 107.0, 105.0, 103.0]
    recent_swing = [101.0, 100.0, 98.0, 96.0, 95.0, 94.0, 93.0, 92.0, 91.0, 90.0]
    bars = make_bars(prior_swing + recent_swing)
    assert detect_reversal(bars, thesis_direction="bullish", swing_lookback=10) is True


def test_no_reversal_for_bullish_thesis_when_still_making_new_highs():
    prior_swing = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 104.0, 103.0, 102.0, 101.0]
    recent_swing = [102.0, 104.0, 106.0, 108.0, 110.0, 112.0, 111.0, 110.0, 109.0, 108.0]
    bars = make_bars(prior_swing + recent_swing)
    assert detect_reversal(bars, thesis_direction="bullish", swing_lookback=10) is False


def test_reversal_detected_for_bearish_thesis_on_higher_high_and_higher_low():
    prior_swing = [110.0, 108.0, 106.0, 104.0, 102.0, 100.0, 101.0, 103.0, 105.0, 107.0]
    recent_swing = [109.0, 110.0, 112.0, 114.0, 115.0, 116.0, 117.0, 118.0, 119.0, 120.0]
    bars = make_bars(prior_swing + recent_swing)
    assert detect_reversal(bars, thesis_direction="bearish", swing_lookback=10) is True


def test_no_reversal_without_enough_history():
    bars = make_bars([100.0] * 15)  # needs 2*swing_lookback == 20
    assert detect_reversal(bars, thesis_direction="bullish", swing_lookback=10) is False


def test_reversal_rejects_invalid_thesis_direction():
    bars = make_bars([100.0] * 25)
    with pytest.raises(ValueError):
        detect_reversal(bars, thesis_direction="sideways", swing_lookback=10)
