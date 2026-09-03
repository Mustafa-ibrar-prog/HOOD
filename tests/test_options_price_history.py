"""Phase 19, Part 17/19 — option OHLC bar and causal-return tests,
including the required lookahead-prevention proofs."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.options.price_history import (
    OptionPriceBar,
    close_to_close_return,
    daily_return_series,
    future_option_return,
    holding_period_return,
)


def _bars(closes: list[float]) -> list[OptionPriceBar]:
    start = date(2022, 1, 3)
    return [OptionPriceBar(date=start + timedelta(days=i), open=c, high=c, low=c, close=c) for i, c in enumerate(closes)]


def test_bar_rejects_high_below_low():
    with pytest.raises(ValueError):
        OptionPriceBar(date=date(2022, 1, 3), open=1.0, high=0.5, low=1.0, close=1.0)


def test_bar_rejects_negative_price():
    with pytest.raises(ValueError):
        OptionPriceBar(date=date(2022, 1, 3), open=-1.0, high=1.0, low=0.0, close=1.0)


def test_bar_has_no_volume_field():
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(OptionPriceBar)}
    assert "volume" not in field_names


def test_close_to_close_return_basic():
    assert close_to_close_return(10.0, 11.0) == pytest.approx(0.1)


def test_close_to_close_return_none_on_zero_base():
    assert close_to_close_return(0.0, 5.0) is None


def test_daily_return_series_first_is_none():
    bars = _bars([1.0, 1.1, 1.21])
    series = daily_return_series(bars)
    assert series[0] is None
    assert series[1] == pytest.approx(0.1)
    assert series[2] == pytest.approx(0.1)
    assert len(series) == len(bars)


def test_future_option_return_basic():
    bars = _bars([10.0, 11.0, 12.0, 13.0])
    out = future_option_return(bars, 1)
    assert out[0] == pytest.approx(0.1)
    assert out[1] == pytest.approx(12.0 / 11.0 - 1.0)
    assert out[-1] is None  # nothing to look forward to


def test_future_option_return_tail_is_none_never_synthesized():
    """Part 17: the tail of a forward-return series must be None, never a
    value silently borrowed from padding, wraparound, or extrapolation."""
    bars = _bars([10.0, 11.0, 12.0])
    for h in (1, 2, 3, 5, 20):
        out = future_option_return(bars, h)
        assert len(out) == len(bars)
        for i in range(len(bars)):
            if i + h >= len(bars):
                assert out[i] is None, f"h={h} i={i} should be None (would look past the series' end)"


def test_future_option_return_rejects_nonpositive_horizon():
    with pytest.raises(ValueError):
        future_option_return(_bars([1.0, 2.0]), 0)


def test_future_option_return_none_on_zero_entry():
    bars = _bars([0.0, 1.0, 2.0])
    out = future_option_return(bars, 1)
    assert out[0] is None


def test_future_option_return_index_alignment_is_exact():
    """Explicit proof that out[i] uses bars[i] as entry and bars[i+h] as
    exit -- not bars[i-1] or bars[i+h-1] or any off-by-one variant."""
    closes = [10.0, 20.0, 40.0, 80.0, 160.0]
    bars = _bars(closes)
    out = future_option_return(bars, 2)
    for i in range(len(bars) - 2):
        expected = (closes[i + 2] - closes[i]) / closes[i]
        assert out[i] == pytest.approx(expected)


def test_holding_period_return_matches_close_to_close():
    assert holding_period_return(10.0, 12.0) == pytest.approx(0.2)


def test_holding_period_return_none_on_zero_entry():
    assert holding_period_return(0.0, 5.0) is None
