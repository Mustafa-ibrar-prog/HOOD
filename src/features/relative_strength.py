"""Phase 12, Part 6: cross-sectional relative-strength features — a NEW
module. Raw momentum reuses Phase 2's RateOfChange(period) directly and
UNMODIFIED (it is already exactly "trailing, causal N-bar return" —
RateOfChange(period)[t] = (close[t]-close[t-period])/close[t-period]),
no new class needed for that piece.

This module adds only what doesn't already exist: a volatility-adjusted
momentum ratio, and two features that describe a stock's OWN momentum
TIME SERIES (persistence, acceleration) — built compositionally on
RateOfChange and Phase 2's RealizedVolatility, both unmodified, following
the exact same "reuse, don't reimplement" convention Phase 9/10's
features modules established.

Cross-sectional / market- and sector-residual construction needs OTHER
symbols' bars too (a market proxy, sector peers) — that doesn't fit the
single-symbol Feature contract, so it lives separately in
src/research/residual_momentum.py, not here.
"""

from __future__ import annotations

from typing import Sequence

from src.data.bar import Bar
from src.features.base import Feature, FeatureSpec
from src.features.momentum import RateOfChange
from src.features.volatility import RealizedVolatility


class VolatilityAdjustedMomentum(Feature):
    """RateOfChange(momentum_window) / RealizedVolatility(vol_window) — a
    momentum reading scaled by trailing (lagged, never same-bar-forward)
    realized volatility, so a large move on a volatile name isn't
    conflated with the same-magnitude move on a quiet one. None when
    volatility is None or exactly 0 (undefined ratio)."""

    def __init__(self, momentum_window: int = 20, vol_window: int = 20):
        if momentum_window < 1:
            raise ValueError("momentum_window must be >= 1")
        self.momentum_window = momentum_window
        self.vol_window = vol_window
        self._mom = RateOfChange(momentum_window)
        self._vol = RealizedVolatility(vol_window)
        self.spec = FeatureSpec(
            name=f"vol_adj_momentum_{momentum_window}", version="1.0", params={"momentum_window": momentum_window, "vol_window": vol_window},
            required_columns=("close",), lookback=max(momentum_window, vol_window),
            description=f"RateOfChange({momentum_window}) / RealizedVolatility({vol_window})",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        mom, vol = self._mom.compute(bars), self._vol.compute(bars)
        return [None if m is None or v is None or v == 0 else m / v for m, v in zip(mom, vol)]


class RelativeStrengthPersistence(Feature):
    """Rolling fraction of the trailing `lookback` bars (including the
    current bar) where RateOfChange(momentum_window) was POSITIVE — an
    OWN-HISTORY sign-persistence measure (has this stock's momentum been
    consistently positive lately), directly analogous to Phase 9's
    RollingFractionAboveThreshold and Phase 10's
    VolatilityPersistenceScore. Explicitly NOT a cross-sectional-rank
    persistence measure (whether the stock stayed in a top quantile
    relative to peers) — that would need panel-level context and is
    computed separately, at the panel level, in the discovery script."""

    def __init__(self, momentum_window: int = 20, lookback: int = 20):
        if lookback < 1:
            raise ValueError("lookback must be >= 1")
        self.momentum_window = momentum_window
        self.lookback = lookback
        self._mom = RateOfChange(momentum_window)
        self.spec = FeatureSpec(
            name="relative_strength_persistence", version="1.0", params={"momentum_window": momentum_window, "lookback": lookback},
            required_columns=("close",), lookback=momentum_window + lookback - 1,
            description=f"fraction of trailing {lookback} bars with RateOfChange({momentum_window}) > 0",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        mom = self._mom.compute(bars)
        flags = [None if v is None else (1.0 if v > 0 else 0.0) for v in mom]
        out: list[float | None] = [None] * len(flags)
        for i in range(len(flags)):
            window_vals = flags[max(0, i - self.lookback + 1) : i + 1]
            if len(window_vals) < self.lookback or any(v is None for v in window_vals):
                continue
            out[i] = sum(window_vals) / self.lookback
        return out


class RelativeStrengthAcceleration(Feature):
    """Discrete second difference of RateOfChange(momentum_window): is
    the stock's own momentum itself speeding up (positive) or slowing
    down (negative)? Directly analogous to Phase 10's
    VolatilityAcceleration, applied to momentum instead of volatility."""

    def __init__(self, momentum_window: int = 20):
        self.momentum_window = momentum_window
        self._mom = RateOfChange(momentum_window)
        self.spec = FeatureSpec(
            name="relative_strength_acceleration", version="1.0", params={"momentum_window": momentum_window},
            required_columns=("close",), lookback=momentum_window + 2,
            description=f"(RateOfChange({momentum_window})[t]-[t-1]) - ([t-1]-[t-2])",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        mom = self._mom.compute(bars)
        out: list[float | None] = [None] * len(mom)
        for i in range(2, len(mom)):
            if mom[i] is not None and mom[i - 1] is not None and mom[i - 2] is not None:
                out[i] = (mom[i] - mom[i - 1]) - (mom[i - 1] - mom[i - 2])
        return out
