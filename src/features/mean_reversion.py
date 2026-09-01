"""Mean-reversion features: rolling z-score, distance from moving average,
and standardized returns. All causal — see src/features/base.py."""

from __future__ import annotations

from typing import Sequence

from src.data.bar import Bar
from src.features._util import mean, pct_change, stdev
from src.features.base import Feature, FeatureSpec
from src.features.momentum import MovingAverageDistance


class RollingZScore(Feature):
    """(close[t] - mean) / stdev over the trailing `window` bars
    (inclusive of t — the window is entirely at-or-before t, so this
    remains causal)."""

    def __init__(self, window: int = 20):
        if window < 2:
            raise ValueError("window must be >= 2")
        self.window = window
        self.spec = FeatureSpec(
            name=f"zscore_{window}",
            version="1.0",
            params={"window": window},
            required_columns=("close",),
            lookback=window - 1,
            description=f"(close[t]-mean)/stdev over the trailing {window}-bar window",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        closes = self._closes(bars)
        out: list[float | None] = [None] * len(closes)
        for i in range(len(closes)):
            if i < self.window - 1:
                continue
            window_vals = closes[i - self.window + 1 : i + 1]
            m, s = mean(window_vals), stdev(window_vals)
            out[i] = None if s == 0 else (closes[i] - m) / s
        return out


class DistanceFromMA(MovingAverageDistance):
    """Re-exported under mean-reversion naming — identical arithmetic to
    momentum.MovingAverageDistance; kept as an independently importable
    name here because it answers a mean-reversion question (how far has
    price stretched from its average) rather than a trend question, even
    though the formula is the same. Given a distinct registered feature
    name (`distance_from_ma_*` instead of `ma_distance_*`) so both can be
    registered on the same FeatureEngine without a name collision."""

    def __init__(self, window: int = 20):
        super().__init__(window)
        self.spec = FeatureSpec(
            name=f"distance_from_ma_{window}",
            version="1.0",
            params={"window": window},
            required_columns=("close",),
            lookback=window - 1,
            description=f"(close[t]-SMA_{window}[t])/SMA_{window}[t] — mean-reversion framing of MovingAverageDistance",
        )


class StandardizedReturns(Feature):
    """z-score of simple returns (period=`return_period`) over the
    trailing `window` bars."""

    def __init__(self, window: int = 20, return_period: int = 1):
        if window < 2:
            raise ValueError("window must be >= 2")
        if return_period < 1:
            raise ValueError("return_period must be >= 1")
        self.window = window
        self.return_period = return_period
        self.spec = FeatureSpec(
            name=f"standardized_return_{return_period}_{window}",
            version="1.0",
            params={"window": window, "return_period": return_period},
            required_columns=("close",),
            lookback=window + return_period - 1,
            description=f"z-score of {return_period}-bar returns over a trailing {window}-bar window",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        rets = pct_change(self._closes(bars), self.return_period)
        out: list[float | None] = [None] * len(rets)
        for i in range(len(rets)):
            if i < self.window - 1:
                continue
            window_vals = rets[i - self.window + 1 : i + 1]
            if any(v is None for v in window_vals):
                continue
            m, s = mean(window_vals), stdev(window_vals)  # type: ignore[arg-type]
            out[i] = None if s == 0 else (rets[i] - m) / s  # type: ignore[operator]
        return out
