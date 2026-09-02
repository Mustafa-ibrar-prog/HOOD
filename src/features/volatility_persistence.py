"""Phase 10, Part 4: volatility-persistence features — a NEW module
(Phase 2's src/features/volatility.py and src/features/regime.py are left
completely untouched) built compositionally on the unmodified
RealizedVolatility (src/features/volatility.py) and VolatilityRegime
(src/features/regime.py), the same "reuse, don't reimplement" convention
used by Phase 9's src/features/volume_clustering.py for RelativeVolume.

Deliberately a COMPACT set (Part 4: "avoid combinatorial feature mining")
— one canonical parameterization per concept, not a sweep of window
sizes. The four `realized_vol_{5,10,20,60}` entries in the preregistered
feature set are just RealizedVolatility(5)/(10)/(20)/(60) directly (no
new class needed).

Every feature follows Phase 2's no-future-data contract: output[i]
depends only on bars[0..i]. tests/test_volatility_persistence_features.py
runs the same leakage-detection methodology as
tests/test_feature_no_lookahead.py against every feature here.
"""

from __future__ import annotations

from typing import Sequence

from src.data.bar import Bar
from src.features._util import mean, percentile_rank, stdev
from src.features.base import Feature, FeatureSpec
from src.features.regime import VolatilityRegime
from src.features.volatility import RealizedVolatility


def _pct_change_allow_none(series: Sequence[float | None], period: int) -> list[float | None]:
    """(series[i]-series[i-period])/series[i-period] — unlike
    src.features._util.pct_change, this explicitly tolerates `series[i]`
    itself being None (RealizedVolatility is None during its own warmup,
    unlike raw volume, which never is)."""
    out: list[float | None] = []
    for i in range(len(series)):
        cur = series[i]
        base = series[i - period] if i >= period else None
        if cur is None or base is None or base == 0:
            out.append(None)
        else:
            out.append((cur - base) / base)
    return out


class VolatilityZScore(Feature):
    """(realized_vol(vol_window)[t] - mean(baseline)) / stdev(baseline),
    baseline = realized_vol(vol_window)[t-vol_window..t-1] — the trailing
    baseline EXCLUDES the current bar's own vol reading, same causal
    convention as Phase 9's VolumeZScore. None when the baseline stdev is
    0 or fewer than `vol_window` prior (defined) vol readings exist."""

    def __init__(self, vol_window: int = 20):
        if vol_window < 2:
            raise ValueError("vol_window must be >= 2")
        self.vol_window = vol_window
        self._rv = RealizedVolatility(vol_window)
        self.spec = FeatureSpec(
            name=f"volatility_zscore_{vol_window}", version="1.0", params={"vol_window": vol_window},
            required_columns=("close",), lookback=2 * vol_window,
            description=f"(realized_vol({vol_window})[t] - mean(baseline)) / stdev(baseline), baseline=trailing {vol_window} prior vol readings",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        rv = self._rv.compute(bars)
        out: list[float | None] = [None] * len(rv)
        for i in range(len(rv)):
            if rv[i] is None:
                continue
            baseline = [v for v in rv[max(0, i - self.vol_window) : i] if v is not None]
            if len(baseline) < self.vol_window:
                continue
            sd = stdev(baseline)
            out[i] = None if sd == 0 else (rv[i] - mean(baseline)) / sd
        return out


class RealizedVolPercentile(Feature):
    """Percentile rank of the current realized_vol(vol_window) value among
    the trailing `lookback` realized_vol(vol_window) values (INCLUDING the
    current bar, same convention as Phase 2's VolatilityPercentile)."""

    def __init__(self, vol_window: int = 20, lookback: int = 60):
        if lookback < 2:
            raise ValueError("lookback must be >= 2")
        self.vol_window = vol_window
        self.lookback = lookback
        self._rv = RealizedVolatility(vol_window)
        self.spec = FeatureSpec(
            name=f"volatility_percentile_{lookback}", version="1.0", params={"vol_window": vol_window, "lookback": lookback},
            required_columns=("close",), lookback=vol_window + lookback - 1,
            description=f"percentile rank of realized_vol({vol_window}) among the trailing {lookback} realized_vol({vol_window}) values",
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


class VolatilityRatio(Feature):
    """realized_vol(short_window)[t] / realized_vol(long_window)[t] — the
    Part 4 "short_long_vol_ratio": > 1 means recent volatility is running
    hotter than the longer-run baseline (a simple term-structure proxy)."""

    def __init__(self, short_window: int = 5, long_window: int = 20):
        if short_window < 2 or long_window < 2:
            raise ValueError("windows must be >= 2")
        if short_window >= long_window:
            raise ValueError("short_window must be < long_window")
        self.short_window = short_window
        self.long_window = long_window
        self._short = RealizedVolatility(short_window)
        self._long = RealizedVolatility(long_window)
        self.spec = FeatureSpec(
            name="short_long_vol_ratio", version="1.0", params={"short_window": short_window, "long_window": long_window},
            required_columns=("close",), lookback=long_window,
            description=f"realized_vol({short_window}) / realized_vol({long_window})",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        short, long = self._short.compute(bars), self._long.compute(bars)
        return [None if s is None or l is None or l == 0 else s / l for s, l in zip(short, long)]


class VolatilityChange(Feature):
    """(realized_vol(vol_window)[t] - realized_vol(vol_window)[t-period]) /
    realized_vol(vol_window)[t-period]."""

    def __init__(self, vol_window: int = 20, period: int = 5):
        if period < 1:
            raise ValueError("period must be >= 1")
        self.vol_window = vol_window
        self.period = period
        self._rv = RealizedVolatility(vol_window)
        self.spec = FeatureSpec(
            name=f"volatility_change_{period}", version="1.0", params={"vol_window": vol_window, "period": period},
            required_columns=("close",), lookback=vol_window + period,
            description=f"(realized_vol({vol_window})[t]-realized_vol({vol_window})[t-{period}])/realized_vol({vol_window})[t-{period}]",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        return _pct_change_allow_none(self._rv.compute(bars), self.period)


class VolatilityAcceleration(Feature):
    """Discrete second difference of realized_vol(vol_window):
    (rv[t]-rv[t-1]) - (rv[t-1]-rv[t-2]) — is volatility's own rate of
    change itself speeding up (positive) or slowing down (negative)?
    Distinct from VolatilityChange, which measures the first difference
    only."""

    def __init__(self, vol_window: int = 20):
        self.vol_window = vol_window
        self._rv = RealizedVolatility(vol_window)
        self.spec = FeatureSpec(
            name="volatility_acceleration", version="1.0", params={"vol_window": vol_window},
            required_columns=("close",), lookback=vol_window + 2,
            description=f"(realized_vol({vol_window})[t]-realized_vol({vol_window})[t-1]) - (realized_vol({vol_window})[t-1]-realized_vol({vol_window})[t-2])",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        rv = self._rv.compute(bars)
        out: list[float | None] = [None] * len(rv)
        for i in range(2, len(rv)):
            if rv[i] is not None and rv[i - 1] is not None and rv[i - 2] is not None:
                out[i] = (rv[i] - rv[i - 1]) - (rv[i - 1] - rv[i - 2])
        return out


class VolatilityPersistenceScore(Feature):
    """Rolling fraction of the trailing `lookback` bars (including the
    current bar) where VolatilityZScore(vol_window) > 0 — i.e. where
    realized vol was running ABOVE its own recent baseline. In [0, 1]:
    1.0 means volatility has been persistently elevated relative to its
    own baseline throughout the whole lookback window (a sustained
    regime, not a one-bar spike), directly analogous to Phase 9's
    RollingFractionAboveThreshold for volume."""

    def __init__(self, vol_window: int = 20, lookback: int = 20):
        if lookback < 1:
            raise ValueError("lookback must be >= 1")
        self.vol_window = vol_window
        self.lookback = lookback
        self._z = VolatilityZScore(vol_window)
        self.spec = FeatureSpec(
            name="volatility_persistence_score", version="1.0", params={"vol_window": vol_window, "lookback": lookback},
            required_columns=("close",), lookback=2 * vol_window + lookback - 1,
            description=f"fraction of trailing {lookback} bars with VolatilityZScore({vol_window}) > 0",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        z = self._z.compute(bars)
        flags = [None if v is None else (1.0 if v > 0 else 0.0) for v in z]
        out: list[float | None] = [None] * len(flags)
        for i in range(len(flags)):
            window_vals = flags[max(0, i - self.lookback + 1) : i + 1]
            if len(window_vals) < self.lookback or any(v is None for v in window_vals):
                continue
            out[i] = sum(window_vals) / self.lookback
        return out


class VolatilityRegimeState(Feature):
    """Thin, name-stable wrapper around the unmodified Phase 2
    VolatilityRegime(window, lookback, n_buckets=4) — buckets 0..3, read
    as LOW/NORMAL/HIGH/EXTREME (the exact, preregistered quartile cut
    points of the trailing `lookback` volatility-percentile distribution:
    bucket 0 = 0th-25th percentile .. bucket 3 = 75th-100th percentile).
    Delegates entirely to the existing, already-tested class — no
    reimplementation."""

    LABELS = ("LOW", "NORMAL", "HIGH", "EXTREME")

    def __init__(self, window: int = 20, lookback: int = 100):
        self.window = window
        self.lookback = lookback
        self._regime = VolatilityRegime(window, lookback, n_buckets=4)
        self.spec = FeatureSpec(
            name="volatility_regime", version="1.0", params={"window": window, "lookback": lookback, "n_buckets": 4},
            required_columns=("close",), lookback=window - 1 + lookback,
            description="VolatilityRegime(window, lookback, n_buckets=4): 0=LOW, 1=NORMAL, 2=HIGH, 3=EXTREME (preregistered quartile cut points)",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        return self._regime.compute(bars)

    @classmethod
    def label_for(cls, bucket: float | None) -> str | None:
        return None if bucket is None else cls.LABELS[int(bucket)]


class VolatilityRegimeDuration(Feature):
    """Current run-length (in bars, including today) of consecutive bars
    with the SAME VolatilityRegimeState bucket value as right now — reset
    to 1 the moment the bucket changes. Answers Part 9's "how long has
    volatility remained in its current regime.\""""

    def __init__(self, window: int = 20, lookback: int = 100):
        self.window = window
        self.lookback = lookback
        self._regime = VolatilityRegimeState(window, lookback)
        self.spec = FeatureSpec(
            name="volatility_regime_duration", version="1.0", params={"window": window, "lookback": lookback},
            required_columns=("close",), lookback=window - 1 + lookback,
            description="consecutive-bar run-length of the current volatility_regime bucket",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        regime = self._regime.compute(bars)
        out: list[float | None] = [None] * len(regime)
        run = 0
        prev = None
        for i, r in enumerate(regime):
            if r is None:
                prev = None
                run = 0
                continue
            run = run + 1 if r == prev else 1
            out[i] = float(run)
            prev = r
        return out


class VolatilityShock(Feature):
    """Binary flag: 1.0 if VolatilityZScore(vol_window) exceeds
    `threshold`, else 0.0. A preregistered, fixed-threshold definition of
    a sudden abnormal-volatility event (Part 3, P10-VP-003)."""

    def __init__(self, vol_window: int = 20, threshold: float = 2.0):
        self.vol_window = vol_window
        self.threshold = threshold
        self._z = VolatilityZScore(vol_window)
        self.spec = FeatureSpec(
            name="volatility_shock", version="1.0", params={"vol_window": vol_window, "threshold": threshold},
            required_columns=("close",), lookback=2 * vol_window,
            description=f"1.0 if VolatilityZScore({vol_window}) > {threshold} else 0.0",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        z = self._z.compute(bars)
        return [None if v is None else (1.0 if v > self.threshold else 0.0) for v in z]


class VolatilityCompression(Feature):
    """Binary flag: 1.0 if RealizedVolPercentile(vol_window, lookback) <=
    `threshold` (Part 11's preregistered "compression" state — a
    low-percentile volatility reading), else 0.0."""

    def __init__(self, vol_window: int = 20, lookback: int = 60, threshold: float = 0.20):
        self.vol_window = vol_window
        self.lookback = lookback
        self.threshold = threshold
        self._pct = RealizedVolPercentile(vol_window, lookback)
        self.spec = FeatureSpec(
            name="volatility_compression", version="1.0", params={"vol_window": vol_window, "lookback": lookback, "threshold": threshold},
            required_columns=("close",), lookback=vol_window + lookback - 1,
            description=f"1.0 if volatility_percentile_{lookback} <= {threshold} else 0.0",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        pct = self._pct.compute(bars)
        return [None if v is None else (1.0 if v <= self.threshold else 0.0) for v in pct]


class VolatilityExpansion(Feature):
    """Binary flag: 1.0 if RealizedVolPercentile(vol_window, lookback) >=
    `threshold` (Part 11's preregistered "expansion" state — a
    high-percentile volatility reading), else 0.0."""

    def __init__(self, vol_window: int = 20, lookback: int = 60, threshold: float = 0.80):
        self.vol_window = vol_window
        self.lookback = lookback
        self.threshold = threshold
        self._pct = RealizedVolPercentile(vol_window, lookback)
        self.spec = FeatureSpec(
            name="volatility_expansion", version="1.0", params={"vol_window": vol_window, "lookback": lookback, "threshold": threshold},
            required_columns=("close",), lookback=vol_window + lookback - 1,
            description=f"1.0 if volatility_percentile_{lookback} >= {threshold} else 0.0",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        pct = self._pct.compute(bars)
        return [None if v is None else (1.0 if v >= self.threshold else 0.0) for v in pct]
