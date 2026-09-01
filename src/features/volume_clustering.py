"""Phase 9, Part 3-4: volume-clustering features — a NEW module (Phase 2's
src/features/volume.py is left completely untouched) built compositionally
on RelativeVolume (src/features/volume.py, unmodified) so every feature
here shares the exact same causal baseline convention: the trailing
average EXCLUDES the current bar.

The point of this whole module is to distinguish a ONE-DAY VOLUME SHOCK
from a PERSISTENT VOLUME CLUSTER — RelativeVolume alone answers "is right
now unusual," these features answer "has UNUSUAL been the norm lately."

Every feature follows Phase 2's no-future-data contract (src/features/base.py):
output[i] depends only on bars[0..i]. tests/test_volume_clustering_features.py
runs the exact same leakage-detection methodology
tests/test_feature_no_lookahead.py already established, against every
feature in this module specifically (Part 4's explicit "create unit tests
proving this").
"""

from __future__ import annotations

import math
from typing import Sequence

from src.data.bar import Bar
from src.features._util import mean, rolling_apply, stdev
from src.features.base import Feature, FeatureSpec
from src.features.volume import RelativeVolume


class LogRelativeVolume(Feature):
    """log(volume[t] / mean(volume[t-window..t-1])) — a log-scaled variant
    of RelativeVolume, built directly on it (genuine reuse, not a
    reimplementation): compresses the right tail of extreme volume spikes,
    which a linear ratio does not."""

    def __init__(self, window: int = 10):
        if window < 1:
            raise ValueError("window must be >= 1")
        self.window = window
        self._rv = RelativeVolume(window)
        self.spec = FeatureSpec(
            name=f"log_relative_volume_{window}", version="1.0", params={"window": window},
            required_columns=("volume",), lookback=window,
            description=f"log(volume[t] / mean(volume[t-{window}..t-1]))",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        rv = self._rv.compute(bars)
        return [None if v is None or v <= 0 else math.log(v) for v in rv]


class VolumeZScore(Feature):
    """(volume[t] - mean(volume[t-window..t-1])) / stdev(volume[t-window..t-1])
    — the trailing baseline EXCLUDES the current bar, same causal
    convention as RelativeVolume. None when the trailing stdev is 0
    (degenerate baseline) or fewer than `window` prior bars exist."""

    def __init__(self, window: int = 20):
        if window < 2:
            raise ValueError("window must be >= 2 (need variance)")
        self.window = window
        self.spec = FeatureSpec(
            name=f"volume_zscore_{window}", version="1.0", params={"window": window},
            required_columns=("volume",), lookback=window,
            description=f"(volume[t] - mean(volume[t-{window}..t-1])) / stdev(volume[t-{window}..t-1])",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        vols = self._volumes(bars)
        out: list[float | None] = [None] * len(vols)
        for i in range(len(vols)):
            if i < self.window:
                continue
            baseline = vols[i - self.window : i]
            sd = stdev(baseline)
            out[i] = None if sd == 0 else (vols[i] - mean(baseline)) / sd
        return out


class VolumeAcceleration(Feature):
    """RelativeVolume(window)[t] - RelativeVolume(window)[t-1] — the
    day-over-day CHANGE in the relative-volume ratio itself (distinct
    from src.features.volume.VolumeChange, which measures change in raw
    volume, not in the already-normalized ratio). Positive = volume
    anomaly intensifying; negative = fading."""

    def __init__(self, window: int = 10):
        if window < 1:
            raise ValueError("window must be >= 1")
        self.window = window
        self._rv = RelativeVolume(window)
        self.spec = FeatureSpec(
            name=f"volume_acceleration_{window}", version="1.0", params={"window": window},
            required_columns=("volume",), lookback=window + 1,
            description=f"RelativeVolume({window})[t] - RelativeVolume({window})[t-1]",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        rv = self._rv.compute(bars)
        out: list[float | None] = [None] * len(rv)
        for i in range(1, len(rv)):
            if rv[i] is not None and rv[i - 1] is not None:
                out[i] = rv[i] - rv[i - 1]
        return out


class RollingFractionAboveThreshold(Feature):
    """Fraction of the trailing `lookback` bars (INCLUDING the current
    bar — this feature is explicitly about "has unusual been the norm
    lately," which by construction must be allowed to see today's own
    reading) where RelativeVolume(base_window) exceeded `threshold`. In
    [0, 1]; 1.0 means every one of the trailing `lookback` bars was
    "abnormal" by this threshold — the signature of a persistent cluster,
    not a one-day shock."""

    def __init__(self, base_window: int = 10, threshold: float = 1.5, lookback: int = 10):
        if lookback < 1:
            raise ValueError("lookback must be >= 1")
        self.base_window = base_window
        self.threshold = threshold
        self.lookback = lookback
        self._rv = RelativeVolume(base_window)
        self.spec = FeatureSpec(
            name=f"volume_frac_above_{base_window}_{threshold:g}_{lookback}", version="1.0",
            params={"base_window": base_window, "threshold": threshold, "lookback": lookback},
            required_columns=("volume",), lookback=base_window + lookback - 1,
            description=f"fraction of trailing {lookback} bars with RelativeVolume({base_window}) > {threshold}",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        rv = self._rv.compute(bars)
        flags = [None if v is None else (1.0 if v > self.threshold else 0.0) for v in rv]
        out: list[float | None] = [None] * len(flags)
        for i in range(len(flags)):
            if i < self.base_window + self.lookback - 1:
                continue
            window_vals = flags[i - self.lookback + 1 : i + 1]
            if any(v is None for v in window_vals):
                continue
            out[i] = sum(window_vals) / self.lookback
        return out


class ConsecutiveAbnormalVolumeStreak(Feature):
    """Current run-length (in bars, INCLUDING today) of consecutive bars
    where RelativeVolume(base_window) > threshold, reset to 0 the moment
    a bar falls at-or-below threshold. A purely causal running counter —
    no fixed lookback window, just "how long has this been going on right
    now.\""""

    def __init__(self, base_window: int = 10, threshold: float = 1.5):
        self.base_window = base_window
        self.threshold = threshold
        self._rv = RelativeVolume(base_window)
        self.spec = FeatureSpec(
            name=f"volume_streak_{base_window}_{threshold:g}", version="1.0",
            params={"base_window": base_window, "threshold": threshold},
            required_columns=("volume",), lookback=base_window,
            description=f"consecutive-bar streak length where RelativeVolume({base_window}) > {threshold}",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        rv = self._rv.compute(bars)
        out: list[float | None] = [None] * len(rv)
        streak = 0
        for i, v in enumerate(rv):
            if v is None:
                continue
            streak = streak + 1 if v > self.threshold else 0
            out[i] = float(streak)
        return out


class RollingMeanRelativeVolume(Feature):
    """Rolling mean of RelativeVolume(base_window) over the trailing
    `lookback` bars (including the current bar) — smooths out single-day
    noise, capturing sustained elevation rather than a one-bar spike."""

    def __init__(self, base_window: int = 10, lookback: int = 10):
        if lookback < 1:
            raise ValueError("lookback must be >= 1")
        self.base_window = base_window
        self.lookback = lookback
        self._rv = RelativeVolume(base_window)
        self.spec = FeatureSpec(
            name=f"volume_rolling_mean_{base_window}_{lookback}", version="1.0",
            params={"base_window": base_window, "lookback": lookback}, required_columns=("volume",),
            lookback=base_window + lookback - 1,
            description=f"rolling mean of RelativeVolume({base_window}) over trailing {lookback} bars",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        rv = self._rv.compute(bars)
        out: list[float | None] = [None] * len(rv)
        for i in range(len(rv)):
            if i < self.base_window + self.lookback - 1:
                continue
            window_vals = rv[i - self.lookback + 1 : i + 1]
            if any(v is None for v in window_vals):
                continue
            out[i] = mean(window_vals)
        return out


class RollingStdRelativeVolume(Feature):
    """Rolling STANDARD DEVIATION of RelativeVolume(base_window) over the
    trailing `lookback` bars — how VARIABLE the volume anomaly itself has
    been, distinct from its level."""

    def __init__(self, base_window: int = 10, lookback: int = 10):
        if lookback < 2:
            raise ValueError("lookback must be >= 2 (need variance)")
        self.base_window = base_window
        self.lookback = lookback
        self._rv = RelativeVolume(base_window)
        self.spec = FeatureSpec(
            name=f"volume_rolling_std_{base_window}_{lookback}", version="1.0",
            params={"base_window": base_window, "lookback": lookback}, required_columns=("volume",),
            lookback=base_window + lookback - 1,
            description=f"rolling stdev of RelativeVolume({base_window}) over trailing {lookback} bars",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        rv = self._rv.compute(bars)
        out: list[float | None] = [None] * len(rv)
        for i in range(len(rv)):
            if i < self.base_window + self.lookback - 1:
                continue
            window_vals = rv[i - self.lookback + 1 : i + 1]
            if any(v is None for v in window_vals):
                continue
            out[i] = stdev(window_vals)
        return out
