"""Focused tests for btc_direction_model.py -- the predictive BTC
direction model. Pure-function/class tests; no run_cycle needed (see
test_polymarket_engine.py for end-to-end wiring)."""

from __future__ import annotations

import math

import pytest

from src.polymarket.btc_direction_model import BtcDirectionModel, BtcDirectionModelError
from src.polymarket.btc_features import BtcFeatureVector
from datetime import datetime, timezone

_T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _vector(**overrides) -> BtcFeatureVector:
    defaults = dict(
        at=_T0, current_price=65_000.0, price_to_beat=64_900.0, distance_from_price_to_beat=100.0,
        distance_from_price_to_beat_pct=100.0 / 64_900.0, time_remaining_seconds=300.0,
        returns={"1m": 0.001, "3m": 0.002, "5m": 0.003, "10m": 0.004, "15m": 0.005},
        momentum_slope_pct=0.0001, realized_volatility=0.001, volume_recent=100.0, volume_acceleration=0.1,
        bar_count=20,
    )
    defaults.update(overrides)
    return BtcFeatureVector(**defaults)


# --- A: untrained model is always a flat 50/50 ------------------------------

def test_a_untrained_model_predicts_a_flat_fifty_fifty():
    model = BtcDirectionModel.untrained()
    assert model.is_trained is False
    prediction = model.predict(_vector())
    assert prediction.predicted_up_probability == pytest.approx(0.5)
    assert prediction.predicted_down_probability == pytest.approx(0.5)
    assert prediction.favored_outcome is None
    assert prediction.is_trained is False


def test_a2_untrained_model_predicts_fifty_fifty_regardless_of_features():
    model = BtcDirectionModel.untrained()
    extreme_vector = _vector(distance_from_price_to_beat_pct=0.5, momentum_slope_pct=10.0)
    prediction = model.predict(extreme_vector)
    assert prediction.predicted_up_probability == pytest.approx(0.5)


# --- B: fit() produces a real, inspectable model ----------------------------

def test_b_fit_on_a_perfectly_separable_dataset_learns_the_right_sign():
    examples = [({"distance_from_price_to_beat_pct": 0.01}, 1), ({"distance_from_price_to_beat_pct": -0.01}, 0)] * 50
    model = BtcDirectionModel.fit(examples, epochs=300, data_source="synthetic")
    assert model.is_trained is True
    assert model.coefficients["distance_from_price_to_beat_pct"] > 0
    assert model.predict_proba({"distance_from_price_to_beat_pct": 0.01}) > 0.5
    assert model.predict_proba({"distance_from_price_to_beat_pct": -0.01}) < 0.5


def test_b2_fit_rejects_an_empty_dataset():
    with pytest.raises(BtcDirectionModelError):
        BtcDirectionModel.fit([], epochs=10)


def test_b3_fit_records_metadata():
    examples = [({"distance_from_price_to_beat_pct": 0.01}, 1)] * 10
    model = BtcDirectionModel.fit(examples, epochs=10, data_source="synthetic")
    assert model.training_example_count == 10
    assert model.data_source == "synthetic"
    assert model.trained_at is not None


# --- C: predict() produces calibrated, complementary probabilities ---------

def test_c_up_and_down_probabilities_always_sum_to_one():
    examples = [({"distance_from_price_to_beat_pct": 0.01}, 1), ({"distance_from_price_to_beat_pct": -0.01}, 0)] * 20
    model = BtcDirectionModel.fit(examples, epochs=100, data_source="synthetic")
    prediction = model.predict(_vector())
    assert prediction.predicted_up_probability + prediction.predicted_down_probability == pytest.approx(1.0)


def test_c2_favored_outcome_matches_the_higher_probability():
    examples = [({"distance_from_price_to_beat_pct": 0.01}, 1), ({"distance_from_price_to_beat_pct": -0.01}, 0)] * 20
    model = BtcDirectionModel.fit(examples, epochs=100, data_source="synthetic")
    up_vector = _vector(distance_from_price_to_beat_pct=0.02)
    prediction = model.predict(up_vector)
    assert prediction.favored_outcome == ("UP" if prediction.predicted_up_probability > 0.5 else "DOWN")


def test_c3_exactly_tied_probability_has_no_favored_outcome():
    model = BtcDirectionModel.untrained()  # always exactly 0.5/0.5
    prediction = model.predict(_vector())
    assert prediction.favored_outcome is None


# --- D: standardization uses the TRAINING set's own mean/stdev --------------

def test_d_a_constant_feature_never_divides_by_zero():
    examples = [({"distance_from_price_to_beat_pct": 0.5}, 1), ({"distance_from_price_to_beat_pct": 0.5}, 0)]
    model = BtcDirectionModel.fit(examples, epochs=10, data_source="synthetic")
    assert model.feature_stdevs["distance_from_price_to_beat_pct"] == pytest.approx(1.0)
    # Must not raise/produce NaN/inf.
    proba = model.predict_proba({"distance_from_price_to_beat_pct": 0.5})
    assert 0.0 <= proba <= 1.0
    assert not math.isnan(proba)


# --- E: persistence (save/load) ----------------------------------------------

def test_e_save_and_load_round_trips_exactly(tmp_path):
    examples = [({"distance_from_price_to_beat_pct": 0.01}, 1), ({"distance_from_price_to_beat_pct": -0.01}, 0)] * 10
    model = BtcDirectionModel.fit(examples, epochs=50, data_source="synthetic")
    path = tmp_path / "model.json"
    model.save(path)
    reloaded = BtcDirectionModel.load(path)
    assert reloaded.is_trained == model.is_trained
    assert reloaded.coefficients == model.coefficients
    assert reloaded.intercept == pytest.approx(model.intercept)
    assert reloaded.data_source == model.data_source
    assert reloaded.predict_proba({"distance_from_price_to_beat_pct": 0.01}) == pytest.approx(
        model.predict_proba({"distance_from_price_to_beat_pct": 0.01})
    )


def test_e2_load_or_untrained_degrades_safely_when_the_path_is_none():
    model = BtcDirectionModel.load_or_untrained(None)
    assert model.is_trained is False


def test_e3_load_or_untrained_degrades_safely_when_the_file_does_not_exist(tmp_path):
    model = BtcDirectionModel.load_or_untrained(tmp_path / "does-not-exist.json")
    assert model.is_trained is False


def test_e4_load_raises_on_a_corrupted_file(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("{not valid json")
    with pytest.raises(BtcDirectionModelError):
        BtcDirectionModel.load(path)


def test_e5_load_rejects_a_model_trained_on_a_different_feature_set(tmp_path):
    path = tmp_path / "model.json"
    path.write_text('{"coefficients": {}, "intercept": 0.0, "feature_means": {}, "feature_stdevs": {}, '
                     '"is_trained": true, "trained_at": "x", "training_example_count": 1, "data_source": "real", '
                     '"feature_names": ["totally_different_feature"]}')
    with pytest.raises(BtcDirectionModelError):
        BtcDirectionModel.load(path)


def test_e6_load_or_untrained_never_masks_a_corrupted_file_as_untrained(tmp_path):
    """A MISSING file degrades safely; a file that EXISTS but is
    corrupted is a real configuration problem and must still raise --
    never silently treated the same as "not configured yet"."""
    path = tmp_path / "corrupt.json"
    path.write_text("{not valid json")
    with pytest.raises(BtcDirectionModelError):
        BtcDirectionModel.load_or_untrained(path)
