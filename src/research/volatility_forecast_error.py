"""Phase 11, Parts 23-24: volatility FORECAST ERROR — mean error, MAE,
RMSE, bias direction, correlation, and a simple calibration check between
a forecast series and the realized outcome it was trying to predict.

Deliberately generic (operates on two aligned Sequence[float | None]),
reused for comparing every candidate forecast (Part 24's baselines:
realized_vol_20, realized_vol_60, a constant historical average, and the
actual forecast used by the chosen exposure mechanism) against the same
realized-volatility ground truth, on the exact same (forecast, realized)
pairs each time — apples to apples.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.research.analysis import mean, pearson_correlation


@dataclass(frozen=True)
class ForecastErrorReport:
    n_observations: int
    mean_error: float | None  # mean(forecast - realized) — positive = forecast OVERESTIMATES on average
    mae: float | None  # mean absolute error
    rmse: float | None  # root mean squared error
    bias_direction: str  # "OVERESTIMATES" | "UNDERESTIMATES" | "UNBIASED" | "NOT_APPLICABLE"
    correlation: float | None  # Pearson correlation between forecast and realized
    calibration_ratio: float | None  # mean(realized) / mean(forecast) — 1.0 = perfectly calibrated on average

    def render(self) -> str:
        def _f(x: float | None) -> str:
            return "None" if x is None else f"{x:.5f}"
        return (f"ForecastError(n={self.n_observations}): mean_error={_f(self.mean_error)} MAE={_f(self.mae)} RMSE={_f(self.rmse)} "
                f"bias={self.bias_direction} corr={_f(self.correlation)} calibration_ratio={_f(self.calibration_ratio)}")


def compute_forecast_error(forecast: Sequence[float | None], realized: Sequence[float | None], *, bias_threshold: float = 0.01) -> ForecastErrorReport:
    """`forecast[i]` and `realized[i]` must already be aligned (same
    index = same point in time / same units — e.g. both per-day realized
    volatility). Rows where either is None are dropped, never imputed."""
    if len(forecast) != len(realized):
        raise ValueError("forecast and realized must be the same length (already aligned by the caller)")
    pairs = [(f, r) for f, r in zip(forecast, realized) if f is not None and r is not None]
    n = len(pairs)
    if n == 0:
        return ForecastErrorReport(0, None, None, None, "NOT_APPLICABLE", None, None)

    errors = [f - r for f, r in pairs]
    mean_error = mean(errors)
    mae = mean([abs(e) for e in errors])
    rmse = mean([e * e for e in errors]) ** 0.5
    if mean_error > bias_threshold:
        bias = "OVERESTIMATES"
    elif mean_error < -bias_threshold:
        bias = "UNDERESTIMATES"
    else:
        bias = "UNBIASED"
    forecasts_only = [f for f, _r in pairs]
    realized_only = [r for _f, r in pairs]
    correlation = pearson_correlation(forecasts_only, realized_only) if n >= 2 else None
    mean_forecast = mean(forecasts_only)
    calibration_ratio = (mean(realized_only) / mean_forecast) if mean_forecast != 0 else None

    return ForecastErrorReport(n_observations=n, mean_error=mean_error, mae=mae, rmse=rmse, bias_direction=bias, correlation=correlation, calibration_ratio=calibration_ratio)
