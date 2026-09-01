"""Volatility features: rolling stdev, realized volatility, ATR, and a
volatility percentile rank. All causal — see src/features/base.py."""

from __future__ import annotations

import math
from typing import Sequence

from src.data.bar import Bar
from src.features._util import mean, percentile_rank, rolling_apply, stdev
from src.features.base import Feature, FeatureSpec


class RollingStd(Feature):
    """Sample standard deviation of close over `window` bars."""

    def __init__(self, window: int = 20):
        if window < 2:
            raise ValueError("window must be >= 2")
        self.window = window
        self.spec = FeatureSpec(
            name=f"rolling_std_{window}",
            version="1.0",
            params={"window": window},
            required_columns=("close",),
            lookback=window - 1,
            description=f"sample stdev of close over {window} bars",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        return rolling_apply(self._closes(bars), self.window, stdev)


class RealizedVolatility(Feature):
    """Rolling stdev of log returns — the standard "realized vol" proxy.
    No annualization is applied unless `annualization_factor` is given
    (e.g. 252 for daily bars); raw per-bar units otherwise."""

    def __init__(self, window: int = 20, annualization_factor: float | None = None):
        if window < 2:
            raise ValueError("window must be >= 2")
        self.window = window
        self.annualization_factor = annualization_factor
        self.spec = FeatureSpec(
            name=f"realized_vol_{window}",
            version="1.0",
            params={"window": window, "annualization_factor": annualization_factor},
            required_columns=("close",),
            lookback=window,
            description="rolling stdev of log returns",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        closes = self._closes(bars)
        log_ret: list[float | None] = [None]
        for i in range(1, len(closes)):
            prev, cur = closes[i - 1], closes[i]
            log_ret.append(None if prev <= 0 or cur <= 0 else math.log(cur / prev))

        out: list[float | None] = [None] * len(closes)
        for i in range(len(closes)):
            if i < self.window:
                continue
            window_vals = log_ret[i - self.window + 1 : i + 1]
            if any(v is None for v in window_vals):
                continue
            vol = stdev(window_vals)  # type: ignore[arg-type]
            out[i] = vol * math.sqrt(self.annualization_factor) if self.annualization_factor else vol
        return out


class ATR(Feature):
    """Average True Range (simple rolling mean of True Range — a
    close-enough, causal variant of Wilder's ATR for research purposes)."""

    def __init__(self, window: int = 14):
        if window < 1:
            raise ValueError("window must be >= 1")
        self.window = window
        self.spec = FeatureSpec(
            name=f"atr_{window}",
            version="1.0",
            params={"window": window},
            required_columns=("high", "low", "close"),
            lookback=window,
            description=f"rolling {window}-bar mean of True Range",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        highs, lows, closes = self._highs(bars), self._lows(bars), self._closes(bars)
        true_range: list[float] = []
        for i in range(len(bars)):
            if i == 0:
                true_range.append(highs[i] - lows[i])
            else:
                prev_close = closes[i - 1]
                true_range.append(max(highs[i] - lows[i], abs(highs[i] - prev_close), abs(lows[i] - prev_close)))
        return rolling_apply(true_range, self.window, mean)


class VolatilityPercentile(Feature):
    """Percentile rank of the current RollingStd value among the trailing
    `lookback` RollingStd values (all strictly at-or-before t — causal)."""

    def __init__(self, window: int = 20, lookback: int = 100):
        if lookback < 2:
            raise ValueError("lookback must be >= 2")
        self.window = window
        self.lookback = lookback
        self._vol = RollingStd(window)
        self.spec = FeatureSpec(
            name=f"vol_percentile_{window}_{lookback}",
            version="1.0",
            params={"window": window, "lookback": lookback},
            required_columns=("close",),
            lookback=window - 1 + lookback,
            description="percentile rank of current rolling-std among the trailing `lookback` rolling-std values",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        vol = self._vol.compute(bars)
        out: list[float | None] = [None] * len(vol)
        for i in range(len(vol)):
            if vol[i] is None:
                continue
            history = [v for v in vol[max(0, i - self.lookback + 1) : i + 1] if v is not None]
            if len(history) < 2:
                continue
            out[i] = percentile_rank(history, vol[i])  # type: ignore[arg-type]
        return out
