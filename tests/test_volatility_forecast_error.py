"""Phase 11, Parts 23-24, 28: volatility forecast-error tests."""

from __future__ import annotations

from src.research.volatility_forecast_error import compute_forecast_error


def test_perfect_forecast_gives_zero_error_and_correlation_one():
    forecast = [0.01, 0.02, 0.015, 0.03, 0.025] * 5
    realized = list(forecast)
    report = compute_forecast_error(forecast, realized)
    assert report.mean_error == 0.0
    assert report.mae == 0.0
    assert report.rmse == 0.0
    assert report.bias_direction == "UNBIASED"
    assert report.correlation is not None and abs(report.correlation - 1.0) < 1e-9
    assert report.calibration_ratio == 1.0


def test_systematic_overestimation_is_flagged():
    realized = [0.01] * 25
    forecast = [0.02] * 25  # always double
    report = compute_forecast_error(forecast, realized)
    assert report.bias_direction == "OVERESTIMATES"
    assert report.mean_error is not None and report.mean_error > 0
    assert report.calibration_ratio == 0.5


def test_systematic_underestimation_is_flagged():
    realized = [0.02] * 25
    forecast = [0.01] * 25
    report = compute_forecast_error(forecast, realized)
    assert report.bias_direction == "UNDERESTIMATES"
    assert report.calibration_ratio == 2.0


def test_mae_and_rmse_hand_computed():
    forecast = [1.0, 2.0, 3.0]
    realized = [2.0, 2.0, 1.0]
    # errors = forecast - realized = [-1, 0, 2]
    report = compute_forecast_error(forecast, realized)
    assert abs(report.mae - (1 + 0 + 2) / 3) < 1e-9
    assert abs(report.rmse - ((1 + 0 + 4) / 3) ** 0.5) < 1e-9


def test_none_values_dropped_not_imputed():
    forecast = [0.01, None, 0.02, 0.03]
    realized = [0.01, 0.02, None, 0.03]
    report = compute_forecast_error(forecast, realized)
    assert report.n_observations == 2  # only indices 0 and 3 have both defined


def test_mismatched_lengths_rejected():
    import pytest

    with pytest.raises(ValueError):
        compute_forecast_error([0.01, 0.02], [0.01])


def test_empty_input_not_applicable():
    report = compute_forecast_error([], [])
    assert report.n_observations == 0
    assert report.bias_direction == "NOT_APPLICABLE"
