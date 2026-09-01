"""Regime features: trend, volatility, and momentum regime classification.
All causal — see src/features/base.py."""

from __future__ import annotations

from typing import Sequence

from src.data.bar import Bar
from src.features.base import Feature, FeatureSpec
from src.features.momentum import MovingAverage, RateOfChange
from src.features.volatility import VolatilityPercentile


class TrendRegime(Feature):
    """1.0 uptrend (fast SMA > slow SMA), -1.0 downtrend, 0.0 neutral/tie.
    None until both moving averages have enough history."""

    def __init__(self, fast_window: int = 10, slow_window: int = 50):
        if fast_window < 1 or slow_window < 1:
            raise ValueError("windows must be >= 1")
        self.fast_window = fast_window
        self.slow_window = slow_window
        self.spec = FeatureSpec(
            name=f"trend_regime_{fast_window}_{slow_window}",
            version="1.0",
            params={"fast_window": fast_window, "slow_window": slow_window},
            required_columns=("close",),
            lookback=max(fast_window, slow_window) - 1,
            description="1.0 uptrend (fast SMA > slow SMA), -1.0 downtrend, 0.0 neutral",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        fast = MovingAverage(self.fast_window).compute(bars)
        slow = MovingAverage(self.slow_window).compute(bars)
        out: list[float | None] = []
        for f, s in zip(fast, slow):
            if f is None or s is None:
                out.append(None)
            elif f > s:
                out.append(1.0)
            elif f < s:
                out.append(-1.0)
            else:
                out.append(0.0)
        return out


class VolatilityRegime(Feature):
    """Volatility percentile bucketed into `n_buckets` regimes: 0 =
    lowest-volatility bucket, n_buckets-1 = highest."""

    def __init__(self, window: int = 20, lookback: int = 100, n_buckets: int = 5):
        if n_buckets < 2:
            raise ValueError("n_buckets must be >= 2")
        self.window = window
        self.lookback = lookback
        self.n_buckets = n_buckets
        self._pct = VolatilityPercentile(window, lookback)
        self.spec = FeatureSpec(
            name=f"vol_regime_{window}_{lookback}_{n_buckets}",
            version="1.0",
            params={"window": window, "lookback": lookback, "n_buckets": n_buckets},
            required_columns=("close",),
            lookback=window - 1 + lookback,
            description=f"volatility percentile bucketed into {n_buckets} regimes (0=lowest .. {n_buckets - 1}=highest)",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        pct = self._pct.compute(bars)
        out: list[float | None] = []
        for p in pct:
            if p is None:
                out.append(None)
            else:
                bucket = min(self.n_buckets - 1, int(p * self.n_buckets))
                out.append(float(bucket))
        return out


class MomentumRegime(Feature):
    """1.0 positive momentum, -1.0 negative, 0.0 flat, based on
    RateOfChange's sign relative to `threshold_pct`."""

    def __init__(self, period: int = 10, threshold_pct: float = 0.0):
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self.threshold_pct = threshold_pct
        self.spec = FeatureSpec(
            name=f"momentum_regime_{period}",
            version="1.0",
            params={"period": period, "threshold_pct": threshold_pct},
            required_columns=("close",),
            lookback=period,
            description="1.0 positive momentum, -1.0 negative, 0.0 flat, from RateOfChange's sign vs. threshold",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        roc = RateOfChange(self.period).compute(bars)
        out: list[float | None] = []
        for r in roc:
            if r is None:
                out.append(None)
            elif r > self.threshold_pct:
                out.append(1.0)
            elif r < -self.threshold_pct:
                out.append(-1.0)
            else:
                out.append(0.0)
        return out
