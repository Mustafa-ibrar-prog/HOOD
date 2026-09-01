"""Momentum features: raw momentum, rate of change, moving averages, and
moving-average distance. All causal — see src/features/base.py."""

from __future__ import annotations

from typing import Sequence

from src.data.bar import Bar
from src.features._util import mean, pct_change, rolling_apply, shifted
from src.features.base import Feature, FeatureSpec


class Momentum(Feature):
    """close[t] - close[t-period], in price units."""

    def __init__(self, period: int = 10):
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self.spec = FeatureSpec(
            name=f"momentum_{period}",
            version="1.0",
            params={"period": period},
            required_columns=("close",),
            lookback=period,
            description=f"close[t]-close[t-{period}]",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        closes = self._closes(bars)
        base = shifted(closes, self.period)
        return [None if b is None else c - b for c, b in zip(closes, base)]


class RateOfChange(Feature):
    """(close[t]/close[t-period] - 1) * 100."""

    def __init__(self, period: int = 10):
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self.spec = FeatureSpec(
            name=f"roc_{period}",
            version="1.0",
            params={"period": period},
            required_columns=("close",),
            lookback=period,
            description=f"(close[t]/close[t-{period}]-1)*100",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        pc = pct_change(self._closes(bars), self.period)
        return [None if v is None else v * 100 for v in pc]


class MovingAverage(Feature):
    """Simple moving average of close over `window` bars."""

    def __init__(self, window: int = 20):
        if window < 1:
            raise ValueError("window must be >= 1")
        self.window = window
        self.spec = FeatureSpec(
            name=f"sma_{window}",
            version="1.0",
            params={"window": window},
            required_columns=("close",),
            lookback=window - 1,
            description=f"simple moving average of close over {window} bars",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        return rolling_apply(self._closes(bars), self.window, mean)


class MovingAverageDistance(Feature):
    """(close[t] - SMA[t]) / SMA[t]."""

    def __init__(self, window: int = 20):
        if window < 1:
            raise ValueError("window must be >= 1")
        self.window = window
        self._ma = MovingAverage(window)
        self.spec = FeatureSpec(
            name=f"ma_distance_{window}",
            version="1.0",
            params={"window": window},
            required_columns=("close",),
            lookback=window - 1,
            description=f"(close[t]-SMA_{window}[t])/SMA_{window}[t]",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        closes = self._closes(bars)
        ma = self._ma.compute(bars)
        out: list[float | None] = []
        for c, m in zip(closes, ma):
            out.append(None if m is None or m == 0 else (c - m) / m)
        return out
