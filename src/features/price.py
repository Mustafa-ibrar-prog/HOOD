"""Price-return features: simple, log, cumulative, and windowed (rolling)
returns. All causal — see src/features/base.py's module docstring."""

from __future__ import annotations

import math
from typing import Sequence

from src.data.bar import Bar
from src.features._util import pct_change, shifted
from src.features.base import Feature, FeatureSpec


class SimpleReturn(Feature):
    """(close[t] - close[t-period]) / close[t-period]."""

    def __init__(self, period: int = 1):
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self.spec = FeatureSpec(
            name=f"simple_return_{period}",
            version="1.0",
            params={"period": period},
            required_columns=("close",),
            lookback=period,
            description=f"(close[t]-close[t-{period}])/close[t-{period}]",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        return pct_change(self._closes(bars), self.period)


class LogReturn(Feature):
    """ln(close[t] / close[t-period])."""

    def __init__(self, period: int = 1):
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self.spec = FeatureSpec(
            name=f"log_return_{period}",
            version="1.0",
            params={"period": period},
            required_columns=("close",),
            lookback=period,
            description=f"ln(close[t]/close[t-{period}])",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        closes = self._closes(bars)
        base = shifted(closes, self.period)
        out: list[float | None] = []
        for c, b in zip(closes, base):
            if b is None or b <= 0 or c <= 0:
                out.append(None)
            else:
                out.append(math.log(c / b))
        return out


class CumulativeReturn(Feature):
    """Running total return since the first bar in the given series:
    close[t]/close[0] - 1. Defined for every bar (including the first,
    where it is 0.0) since it needs no history beyond the series' own
    start — a genuinely different question from a fixed-window return."""

    def __init__(self):
        self.spec = FeatureSpec(
            name="cumulative_return",
            version="1.0",
            params={},
            required_columns=("close",),
            lookback=0,
            description="close[t]/close[0] - 1",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        closes = self._closes(bars)
        if not closes:
            return []
        base = closes[0]
        if base <= 0:
            return [None] * len(closes)
        return [c / base - 1 for c in closes]


class RollingReturn(SimpleReturn):
    """Total return over a trailing fixed-size window — same arithmetic as
    SimpleReturn, kept as a distinctly-named/registered feature because
    "return over my lookback window" is a different research question than
    "1-bar return" even though the formula is identical."""

    def __init__(self, window: int):
        super().__init__(period=window)
        self.window = window
        self.spec = FeatureSpec(
            name=f"rolling_return_{window}",
            version="1.0",
            params={"window": window},
            required_columns=("close",),
            lookback=window,
            description=f"total return over the trailing {window}-bar window",
        )
