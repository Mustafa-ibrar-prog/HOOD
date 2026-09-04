"""Phase 31, Parts 2 & 7/18 — underlying-only control and the causal
residual-return benchmark model."""

from __future__ import annotations

import random
from datetime import date, datetime, timezone

from src.options.mechanical_baseline import BaselineClassification
from src.options.phase31_underlying_control import (
    economically_scoped_rows,
    ols_fit,
    residualize_against_underlying,
    underlying_control_comparison,
)


def _row(ts, underlying, expiration, feature, underlying_ret, target):
    return {
        "timestamp": ts, "underlying_symbol": underlying, "symbol": underlying,
        "cs_group_key": (underlying, expiration, ts),
        "option_feature": feature, "forward_underlying_return_5": underlying_ret, "forward_option_return_5": target,
    }


def test_ols_fit_recovers_a_perfect_linear_relationship():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [2 * x + 1 for x in xs]  # y = 1 + 2x exactly
    fit = ols_fit([xs], ys)
    assert fit is not None
    coeffs, r2 = fit
    assert abs(coeffs[0] - 1.0) < 1e-9
    assert abs(coeffs[1] - 2.0) < 1e-9
    assert abs(r2 - 1.0) < 1e-9


def test_ols_fit_returns_none_with_too_few_observations():
    assert ols_fit([[1.0, 2.0]], [1.0, 2.0]) is None


def test_ols_fit_handles_two_features():
    rng = random.Random(7)
    xs1 = [rng.uniform(-1, 1) for _ in range(50)]
    xs2 = [rng.uniform(-1, 1) for _ in range(50)]
    ys = [1.0 + 2.0 * a + 3.0 * b for a, b in zip(xs1, xs2)]
    fit = ols_fit([xs1, xs2], ys)
    coeffs, r2 = fit
    assert abs(coeffs[0] - 1.0) < 1e-6
    assert abs(coeffs[1] - 2.0) < 1e-6
    assert abs(coeffs[2] - 3.0) < 1e-6
    assert r2 > 0.999


def test_economically_scoped_rows_preserves_real_timestamp():
    rows = [_row(datetime(2026, 1, 1, tzinfo=timezone.utc), "AAPL", "2026-12-18", 0.1, 0.01, 0.02)]
    scoped = economically_scoped_rows(rows)
    assert scoped[0]["timestamp"] == rows[0]["cs_group_key"]
    assert scoped[0]["_real_timestamp"] == rows[0]["timestamp"]
    assert rows[0]["timestamp"] != rows[0]["cs_group_key"]  # original untouched


def test_underlying_control_delta_r_squared_when_feature_adds_real_signal():
    rng = random.Random(11)
    rows = []
    for i in range(80):
        ts = datetime(2026, 1, 1 + (i % 27), tzinfo=timezone.utc)
        underlying_ret = rng.uniform(-0.05, 0.05)
        feature = rng.uniform(-1, 1)
        target = 0.5 * underlying_ret + 0.3 * feature + rng.gauss(0, 0.001)  # feature genuinely predictive
        rows.append(_row(ts, "AAPL", "2026-12-18", feature, underlying_ret, target))

    report = underlying_control_comparison(
        rows, option_feature_col="option_feature", target_col="forward_option_return_5",
        underlying_return_col="forward_underlying_return_5", underlying_target_col="forward_underlying_return_5",
    )
    assert report.n == 80
    assert report.model_b_r_squared > report.model_a_r_squared
    assert report.delta_r_squared > 0.05


def test_underlying_control_classification_reuses_mechanical_baseline():
    rows = []
    rng = random.Random(3)
    for i in range(60):
        ts = datetime(2026, 1, 1 + (i % 27), tzinfo=timezone.utc)
        underlying_ret = rng.uniform(-0.05, 0.05)
        feature = underlying_ret * 2  # feature is just a scaled copy of the underlying return -- pure inheritance
        target = underlying_ret + rng.gauss(0, 0.0001)
        rows.append(_row(ts, "AAPL", "2026-12-18", feature, underlying_ret, target))
    report = underlying_control_comparison(
        rows, option_feature_col="option_feature", target_col="forward_option_return_5",
        underlying_return_col="forward_underlying_return_5", underlying_target_col="forward_underlying_return_5",
    )
    assert report.classification in (BaselineClassification.INHERITED_FROM_UNDERLYING, BaselineClassification.BOTH_WEAK_OR_UNDEFINED)


def test_residualize_against_underlying_drops_the_linear_component():
    rng = random.Random(5)
    rows = []
    for i in range(50):
        ts = datetime(2026, 1, 1 + (i % 27), tzinfo=timezone.utc)
        underlying_ret = rng.uniform(-0.05, 0.05)
        option_ret = 2.0 * underlying_ret + 5.0  # perfectly linear in the underlying return
        rows.append({"forward_underlying_return_5": underlying_ret, "forward_option_return_5": option_ret})
    residualized = residualize_against_underlying(rows, option_target_col="forward_option_return_5", underlying_target_col="forward_underlying_return_5")
    for r in residualized:
        assert abs(r["forward_option_return_5_residualized"]) < 1e-6  # perfectly explained -> ~0 residual


def test_residualize_never_mutates_input_rows():
    rows = [{"forward_underlying_return_5": 0.01, "forward_option_return_5": 0.02}] * 10
    original_keys = set(rows[0].keys())
    residualize_against_underlying(rows, option_target_col="forward_option_return_5", underlying_target_col="forward_underlying_return_5")
    assert set(rows[0].keys()) == original_keys


def test_residualize_none_for_rows_missing_either_input():
    rows = [
        {"forward_underlying_return_5": 0.01, "forward_option_return_5": 0.02},
        {"forward_underlying_return_5": None, "forward_option_return_5": 0.02},
        {"forward_underlying_return_5": 0.01, "forward_option_return_5": None},
    ]
    residualized = residualize_against_underlying(rows, option_target_col="forward_option_return_5", underlying_target_col="forward_underlying_return_5")
    assert residualized[1]["forward_option_return_5_residualized"] is None
    assert residualized[2]["forward_option_return_5_residualized"] is None
