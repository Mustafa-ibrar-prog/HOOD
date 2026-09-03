"""Phase 19, Part 3/19 — the combined option-contract research
observation (OHLC + underlying close reference + moneyness + DTE +
forward returns)."""

from __future__ import annotations

from datetime import date, timedelta

from src.options.expiration import DTEBucket
from src.options.instrument import OptionContract
from src.options.moneyness import MoneynessBucket
from src.options.price_history import OptionPriceBar
from src.options.research_observation import OptionResearchObservation, build_research_series

CONTRACT = OptionContract(underlying_symbol="AAPL", option_id="c1", call_put="call", strike=150.0, expiration=date(2022, 1, 21))


def test_build_single_observation():
    bar = OptionPriceBar(date=date(2022, 1, 3), open=5.0, high=5.5, low=4.5, close=5.0)
    obs = OptionResearchObservation.build(contract=CONTRACT, option_bar=bar, underlying_close=165.0)
    assert obs.dte == 18
    assert obs.dte_bucket == DTEBucket.EIGHT_TO_THIRTY
    assert obs.moneyness.bucket in (MoneynessBucket.ITM, MoneynessBucket.DEEP_ITM)
    assert obs.observation_date == date(2022, 1, 3)
    assert obs.forward_returns == {}


def _daily_bars(start: date, closes: list[float]) -> list[OptionPriceBar]:
    return [OptionPriceBar(date=start + timedelta(days=i), open=c, high=c, low=c, close=c) for i, c in enumerate(closes)]


def test_build_research_series_computes_forward_returns():
    start = date(2022, 1, 3)
    option_bars = _daily_bars(start, [5.0, 5.5, 6.0, 6.6])
    underlying_closes = {start + timedelta(days=i): 160.0 + i for i in range(4)}
    series = build_research_series(contract=CONTRACT, option_bars=option_bars, underlying_closes_by_date=underlying_closes, horizons=(1, 2))
    assert len(series) == 4
    assert series[0].forward_returns[1] == (5.5 - 5.0) / 5.0
    assert series[0].forward_returns[2] == (6.0 - 5.0) / 5.0
    assert series[-1].forward_returns[1] is None  # tail -- no future data
    assert series[-1].forward_returns[2] is None


def test_build_research_series_drops_bars_with_no_matching_underlying_close():
    start = date(2022, 1, 3)
    option_bars = _daily_bars(start, [5.0, 5.5, 6.0])
    underlying_closes = {start: 160.0, start + timedelta(days=2): 162.0}  # day 1 is missing
    series = build_research_series(contract=CONTRACT, option_bars=option_bars, underlying_closes_by_date=underlying_closes, horizons=(1,))
    dates_present = {obs.observation_date for obs in series}
    assert start + timedelta(days=1) not in dates_present
    assert len(series) == 2


def test_underlying_close_is_a_reference_not_a_duplicated_bar_object():
    bar = OptionPriceBar(date=date(2022, 1, 3), open=5.0, high=5.5, low=4.5, close=5.0)
    obs = OptionResearchObservation.build(contract=CONTRACT, option_bar=bar, underlying_close=165.0)
    assert isinstance(obs.underlying_close, float)
    assert obs.underlying_close == 165.0
