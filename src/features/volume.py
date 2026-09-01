"""Volume features: rolling volume, volume change, relative volume, and a
volume percentile rank. All causal — see src/features/base.py."""

from __future__ import annotations

from typing import Sequence

from src.data.bar import Bar
from src.features._util import mean, pct_change, percentile_rank, rolling_apply
from src.features.base import Feature, FeatureSpec


class RollingVolume(Feature):
    """Simple moving average of volume over `window` bars."""

    def __init__(self, window: int = 20):
        if window < 1:
            raise ValueError("window must be >= 1")
        self.window = window
        self.spec = FeatureSpec(
            name=f"rolling_volume_{window}",
            version="1.0",
            params={"window": window},
            required_columns=("volume",),
            lookback=window - 1,
            description=f"SMA of volume over {window} bars",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        return rolling_apply(self._volumes(bars), self.window, mean)


class VolumeChange(Feature):
    """(volume[t] - volume[t-period]) / volume[t-period]."""

    def __init__(self, period: int = 1):
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self.spec = FeatureSpec(
            name=f"volume_change_{period}",
            version="1.0",
            params={"period": period},
            required_columns=("volume",),
            lookback=period,
            description=f"(volume[t]-volume[t-{period}])/volume[t-{period}]",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        return pct_change(self._volumes(bars), self.period)


class RelativeVolume(Feature):
    """volume[t] / mean(volume[t-window .. t-1]) — the trailing average
    EXCLUDES the current bar, so this is a genuinely causal "how does
    right-now compare to the recent past" measure, not a same-bar
    self-reference."""

    def __init__(self, window: int = 20):
        if window < 1:
            raise ValueError("window must be >= 1")
        self.window = window
        self.spec = FeatureSpec(
            name=f"relative_volume_{window}",
            version="1.0",
            params={"window": window},
            required_columns=("volume",),
            lookback=window,
            description=f"volume[t] / mean(volume[t-{window}..t-1])",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        vols = self._volumes(bars)
        out: list[float | None] = [None] * len(vols)
        for i in range(len(vols)):
            if i < self.window:
                continue
            avg = mean(vols[i - self.window : i])
            out[i] = None if avg == 0 else vols[i] / avg
        return out


class VolumePercentile(Feature):
    """Percentile rank of the current RollingVolume value among the
    trailing `lookback` RollingVolume values (causal)."""

    def __init__(self, window: int = 20, lookback: int = 100):
        if lookback < 2:
            raise ValueError("lookback must be >= 2")
        self.window = window
        self.lookback = lookback
        self._rv = RollingVolume(window)
        self.spec = FeatureSpec(
            name=f"volume_percentile_{window}_{lookback}",
            version="1.0",
            params={"window": window, "lookback": lookback},
            required_columns=("volume",),
            lookback=window - 1 + lookback,
            description="percentile rank of current rolling-volume among the trailing `lookback` rolling-volume values",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        rv = self._rv.compute(bars)
        out: list[float | None] = [None] * len(rv)
        for i in range(len(rv)):
            if rv[i] is None:
                continue
            history = [v for v in rv[max(0, i - self.lookback + 1) : i + 1] if v is not None]
            if len(history) < 2:
                continue
            out[i] = percentile_rank(history, rv[i])  # type: ignore[arg-type]
        return out
