"""Focused tests for btc_features.py -- causal feature computation
for the predictive BTC direction model. Pure-function tests against
hand-built PriceBar sequences; no run_cycle needed (see
test_polymarket_engine.py for end-to-end wiring)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.market.models import PriceBar
from src.polymarket.btc_features import compute_btc_features, resolve_price_to_beat
from src.polymarket.btc_market_data import BtcQuoteSample

_T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _flat_bars(*, start: datetime, minutes: int, price: float = 65_000.0) -> list[PriceBar]:
    return [
        PriceBar(start_time=start + timedelta(minutes=i), open=price, high=price, low=price, close=price, volume=10.0)
        for i in range(minutes)
    ]


def _rising_bars(*, start: datetime, minutes: int, start_price: float = 65_000.0, step: float = 10.0) -> list[PriceBar]:
    return [
        PriceBar(
            start_time=start + timedelta(minutes=i), open=start_price + i * step, high=start_price + i * step,
            low=start_price + i * step, close=start_price + i * step, volume=10.0 + i,
        )
        for i in range(minutes)
    ]


# --- A: no look-ahead -- only bars strictly before `at` are ever used ------

def test_a_a_bar_at_or_after_at_is_never_used():
    bars = _flat_bars(start=_T0, minutes=20)
    future_bar = PriceBar(start_time=_T0 + timedelta(minutes=20), open=999_999.0, high=999_999.0, low=999_999.0, close=999_999.0, volume=1.0)
    at = _T0 + timedelta(minutes=20)
    without_future = compute_btc_features(bars, at=at, price_to_beat=65_000.0, close_time=at + timedelta(minutes=5))
    with_future = compute_btc_features(bars + [future_bar], at=at, price_to_beat=65_000.0, close_time=at + timedelta(minutes=5))
    assert without_future.current_price == with_future.current_price  # the future bar changed nothing
    assert with_future.current_price != 999_999.0


def test_a2_bars_out_of_order_are_still_handled_correctly():
    bars = _flat_bars(start=_T0, minutes=20)
    at = _T0 + timedelta(minutes=20)
    ordered = compute_btc_features(bars, at=at, price_to_beat=65_000.0, close_time=at)
    shuffled = compute_btc_features(list(reversed(bars)), at=at, price_to_beat=65_000.0, close_time=at)
    assert ordered.current_price == shuffled.current_price
    assert ordered.returns == shuffled.returns


# --- B: time remaining ------------------------------------------------------

def test_b_time_remaining_is_close_time_minus_at():
    bars = _flat_bars(start=_T0, minutes=20)
    at = _T0 + timedelta(minutes=20)
    close_time = at + timedelta(minutes=7)
    features = compute_btc_features(bars, at=at, price_to_beat=65_000.0, close_time=close_time)
    assert features.time_remaining_seconds == pytest.approx(420.0)


def test_b2_time_remaining_never_negative_past_close():
    bars = _flat_bars(start=_T0, minutes=20)
    at = _T0 + timedelta(minutes=20)
    close_time = at - timedelta(minutes=1)  # already closed
    features = compute_btc_features(bars, at=at, price_to_beat=65_000.0, close_time=close_time)
    assert features.time_remaining_seconds == 0.0


# --- C: distance from price-to-beat -----------------------------------------

def test_c_distance_from_price_to_beat_in_dollars_and_pct():
    bars = _flat_bars(start=_T0, minutes=20, price=66_000.0)
    at = _T0 + timedelta(minutes=20)
    features = compute_btc_features(bars, at=at, price_to_beat=65_000.0, close_time=at + timedelta(minutes=5))
    assert features.current_price == pytest.approx(66_000.0)
    assert features.distance_from_price_to_beat == pytest.approx(1_000.0)
    assert features.distance_from_price_to_beat_pct == pytest.approx(1_000.0 / 65_000.0)


def test_c2_no_price_to_beat_is_none_distance_never_guessed():
    bars = _flat_bars(start=_T0, minutes=20)
    at = _T0 + timedelta(minutes=20)
    features = compute_btc_features(bars, at=at, price_to_beat=None, close_time=at + timedelta(minutes=5))
    assert features.distance_from_price_to_beat is None
    assert features.distance_from_price_to_beat_pct is None
    assert not features.has_minimum_data


# --- D: returns over each configured window ---------------------------------

def test_d_returns_computed_correctly_over_each_window():
    bars = _rising_bars(start=_T0, minutes=20, start_price=65_000.0, step=10.0)
    at = _T0 + timedelta(minutes=20)
    features = compute_btc_features(bars, at=at, price_to_beat=65_000.0, close_time=at + timedelta(minutes=5))
    # current_price is bars[19].close = 65_000 + 19*10 = 65_190
    assert features.current_price == pytest.approx(65_190.0)
    # 1m ago -> bars[18].close = 65_180 -> return = (65190-65180)/65180
    assert features.returns["1m"] == pytest.approx((65_190.0 - 65_180.0) / 65_180.0)
    # 15m ago -> bars[4].close = 65_040
    assert features.returns["15m"] == pytest.approx((65_190.0 - 65_040.0) / 65_040.0)


def test_d2_insufficient_history_leaves_longer_returns_none():
    bars = _flat_bars(start=_T0, minutes=5)  # only 5 minutes of history
    at = _T0 + timedelta(minutes=5)
    features = compute_btc_features(bars, at=at, price_to_beat=65_000.0, close_time=at + timedelta(minutes=5))
    assert features.returns["1m"] is not None
    assert features.returns["15m"] is None
    assert not features.has_minimum_data  # the longest window (15m) gates has_minimum_data


# --- E: has_minimum_data is the hard floor -----------------------------------

def test_e_has_minimum_data_true_only_with_price_current_time_and_15m_history():
    bars = _flat_bars(start=_T0, minutes=20)
    at = _T0 + timedelta(minutes=20)
    features = compute_btc_features(bars, at=at, price_to_beat=65_000.0, close_time=at + timedelta(minutes=5))
    assert features.has_minimum_data


def test_e2_no_bars_at_all_has_minimum_data_false():
    at = _T0 + timedelta(minutes=20)
    features = compute_btc_features([], at=at, price_to_beat=65_000.0, close_time=at + timedelta(minutes=5))
    assert features.current_price is None
    assert not features.has_minimum_data
    assert features.bar_count == 0


# --- F: momentum slope -------------------------------------------------------

def test_f_rising_prices_yield_a_positive_momentum_slope():
    bars = _rising_bars(start=_T0, minutes=20, step=10.0)
    at = _T0 + timedelta(minutes=20)
    features = compute_btc_features(bars, at=at, price_to_beat=65_000.0, close_time=at + timedelta(minutes=5))
    assert features.momentum_slope_pct > 0


def test_f2_flat_prices_yield_a_zero_momentum_slope():
    bars = _flat_bars(start=_T0, minutes=20)
    at = _T0 + timedelta(minutes=20)
    features = compute_btc_features(bars, at=at, price_to_beat=65_000.0, close_time=at + timedelta(minutes=5))
    assert features.momentum_slope_pct == pytest.approx(0.0)


# --- G: realized volatility ---------------------------------------------------

def test_g_flat_prices_yield_zero_realized_volatility():
    bars = _flat_bars(start=_T0, minutes=20)
    at = _T0 + timedelta(minutes=20)
    features = compute_btc_features(bars, at=at, price_to_beat=65_000.0, close_time=at + timedelta(minutes=5))
    assert features.realized_volatility == pytest.approx(0.0)


def test_g2_volatile_prices_yield_positive_realized_volatility():
    start = _T0
    bars = []
    price = 65_000.0
    for i in range(20):
        price = 65_000.0 + (500.0 if i % 2 == 0 else -500.0)
        bars.append(PriceBar(start_time=start + timedelta(minutes=i), open=price, high=price, low=price, close=price, volume=10.0))
    at = start + timedelta(minutes=20)
    features = compute_btc_features(bars, at=at, price_to_beat=65_000.0, close_time=at + timedelta(minutes=5))
    assert features.realized_volatility > 0


# --- H: volume acceleration ---------------------------------------------------

def test_h_increasing_volume_yields_positive_volume_acceleration():
    bars = _rising_bars(start=_T0, minutes=20, step=0.0)  # flat price, rising volume
    at = _T0 + timedelta(minutes=20)
    features = compute_btc_features(bars, at=at, price_to_beat=65_000.0, close_time=at + timedelta(minutes=5))
    assert features.volume_acceleration > 0


# --- I: as_feature_dict() imputes None to 0.0, never raises ------------------

def test_i_as_feature_dict_imputes_missing_values_to_zero():
    at = _T0 + timedelta(minutes=5)
    features = compute_btc_features([], at=at, price_to_beat=None, close_time=at + timedelta(minutes=5))
    feature_dict = features.as_feature_dict()
    assert feature_dict["distance_from_price_to_beat_pct"] == 0.0
    assert feature_dict["return_15m"] == 0.0
    assert all(isinstance(v, float) for v in feature_dict.values())


def test_i2_feature_dict_keys_match_feature_names_exactly():
    from src.polymarket.btc_features import FEATURE_NAMES
    at = _T0 + timedelta(minutes=20)
    features = compute_btc_features(_flat_bars(start=_T0, minutes=20), at=at, price_to_beat=65_000.0, close_time=at)
    assert set(features.as_feature_dict().keys()) == set(FEATURE_NAMES)


# --- J: resolve_price_to_beat() ----------------------------------------------

def test_j_resolves_from_a_bar_exactly_at_window_start():
    window_start = _T0
    bars = _flat_bars(start=window_start, minutes=5, price=64_500.0)
    result = resolve_price_to_beat(bars=bars, raw_samples=None, window_start=window_start)
    assert result == pytest.approx(64_500.0)


def test_j2_falls_back_to_the_earliest_raw_sample_at_or_after_window_start():
    window_start = _T0
    samples = [
        BtcQuoteSample(price=64_100.0, observed_at=window_start - timedelta(seconds=5)),  # before -- never used
        BtcQuoteSample(price=64_200.0, observed_at=window_start + timedelta(seconds=2)),  # earliest at/after
        BtcQuoteSample(price=64_300.0, observed_at=window_start + timedelta(seconds=10)),
    ]
    result = resolve_price_to_beat(bars=[], raw_samples=samples, window_start=window_start)
    assert result == pytest.approx(64_200.0)


def test_j3_none_when_neither_a_bar_nor_a_sample_is_available():
    window_start = _T0
    result = resolve_price_to_beat(bars=[], raw_samples=None, window_start=window_start)
    assert result is None


def test_j4_a_bar_exactly_at_window_start_is_preferred_over_raw_samples():
    window_start = _T0
    bars = _flat_bars(start=window_start, minutes=1, price=64_500.0)
    samples = [BtcQuoteSample(price=99_999.0, observed_at=window_start)]
    result = resolve_price_to_beat(bars=bars, raw_samples=samples, window_start=window_start)
    assert result == pytest.approx(64_500.0)  # the bar, never the sample, when both exist
