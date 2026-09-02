"""Phase 11, Parts 4-7: preregistered EXPOSURE mechanisms — pure,
causal functions that turn already-computed, causal feature values into
an exposure FRACTION in [EXPOSURE_MIN, EXPOSURE_MAX] (Part 6's "clamp to
minimum/maximum exposure, all limits preregistered").

CRITICAL DISTINCTION (the phase's own framing): these functions modify
EXPOSURE (how much of the equal-weight/benchmark allocation to hold),
never DIRECTION (every mechanism here only ever proposes LONG at some
fraction — there is no short, no market-timing reversal). Reuses Phase 2's
FeatureEngine and Phase 9/10's already-tested, UNMODIFIED volatility
features (RealizedVolatility via the new AnnualizedRealizedVolatility
wrapper, VolatilityRegimeState, VolatilityCompression, VolatilityExpansion)
— nothing here reimplements volatility measurement, only the EXPOSURE
POLICY built on top of it.

`compute_exposure_series` is deliberately a STANDALONE, precomputed
function (not logic embedded live inside a BacktestStrategy.generate_signal
call) — see src/research/exposure_strategy.py's module docstring for why:
it makes the shuffled/randomized placebo controls (Parts 25-26) trivial and
exactly comparable (same rebalance timestamps, same value distribution),
and it is independently no-lookahead-testable exactly like any Feature
(tests/test_exposure_mechanisms.py runs the same mutate-the-future
methodology as tests/test_feature_no_lookahead.py).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from src.data.bar import Bar
from src.features.annualized_volatility import AnnualizedRealizedVolatility
from src.features.engine import FeatureEngine
from src.features.volatility_persistence import VolatilityCompression, VolatilityExpansion, VolatilityRegimeState

# --- preregistered constants (Part 4, 6) — FIXED before any backtest ran ------------------------
EXPOSURE_MIN = 0.10  # a 10% floor — this phase never goes fully flat/short, only scales a long allocation
EXPOSURE_MAX = 1.00  # a hard 100% cap — NO LEVERAGE anywhere in this phase, a deliberate, conservative design choice
TARGET_VOL_CANDIDATES = (0.10, 0.15, 0.20)  # annualized (Part 18)
REBALANCE_FREQUENCIES = {"daily": 1, "weekly": 5}  # in bars (Part 7, 19) — an approximate trading week, not calendar-day-of-week dependent
REGIME_EXPOSURE = {"LOW": 1.00, "NORMAL": 1.00, "HIGH": 0.50, "EXTREME": 0.25}  # Part 4's exact example mapping
COMPRESSION_EXPANSION_EXPOSURE = {"COMPRESSION": 1.00, "EXPANSION": 0.50, "NEITHER": 1.00}  # Part 4's "preregistered exposure adjustments"
MECHANISMS = ("STATIC", "VOL_TARGET", "REGIME", "COMPRESSION_EXPANSION")
VOL_REGIME_LABELS = {0.0: "LOW", 1.0: "NORMAL", 2.0: "HIGH", 3.0: "EXTREME"}


def _clamp(x: float) -> float:
    return max(EXPOSURE_MIN, min(EXPOSURE_MAX, x))


@dataclass(frozen=True)
class ExposureMechanismConfig:
    mechanism: str  # one of MECHANISMS
    target_annual_vol: float | None = None  # required for VOL_TARGET
    rebalance_frequency: str = "weekly"  # key into REBALANCE_FREQUENCIES

    def __post_init__(self) -> None:
        if self.mechanism not in MECHANISMS:
            raise ValueError(f"mechanism must be one of {MECHANISMS}, got {self.mechanism!r}")
        if self.mechanism == "VOL_TARGET" and self.target_annual_vol is None:
            raise ValueError("VOL_TARGET requires target_annual_vol")
        if self.rebalance_frequency not in REBALANCE_FREQUENCIES:
            raise ValueError(f"rebalance_frequency must be one of {tuple(REBALANCE_FREQUENCIES)}, got {self.rebalance_frequency!r}")

    @property
    def label(self) -> str:
        if self.mechanism == "VOL_TARGET":
            return f"VOL_TARGET({self.target_annual_vol:.0%})/{self.rebalance_frequency}"
        return f"{self.mechanism}/{self.rebalance_frequency}"


def _static_exposure(row: Mapping[str, float | None]) -> float | None:
    return EXPOSURE_MAX


def _vol_target_exposure(row: Mapping[str, float | None], *, target_annual_vol: float) -> float | None:
    forecast = row.get("realized_vol_20_ann")
    if forecast is None or forecast <= 0:
        return None
    return _clamp(target_annual_vol / forecast)


def _regime_exposure(row: Mapping[str, float | None]) -> float | None:
    label = VOL_REGIME_LABELS.get(row.get("volatility_regime"))
    if label is None:
        return None
    return _clamp(REGIME_EXPOSURE[label])


def _compression_expansion_exposure(row: Mapping[str, float | None]) -> float | None:
    if row.get("volatility_compression") is None or row.get("volatility_expansion") is None:
        return None
    if row["volatility_compression"] == 1.0:
        return _clamp(COMPRESSION_EXPANSION_EXPOSURE["COMPRESSION"])
    if row["volatility_expansion"] == 1.0:
        return _clamp(COMPRESSION_EXPANSION_EXPOSURE["EXPANSION"])
    return _clamp(COMPRESSION_EXPANSION_EXPOSURE["NEITHER"])


_DISPATCH = {"STATIC": _static_exposure, "VOL_TARGET": _vol_target_exposure, "REGIME": _regime_exposure, "COMPRESSION_EXPANSION": _compression_expansion_exposure}


def _feature_engine() -> FeatureEngine:
    return FeatureEngine([AnnualizedRealizedVolatility(20), VolatilityRegimeState(window=20, lookback=100), VolatilityCompression(vol_window=20, lookback=60, threshold=0.20), VolatilityExpansion(vol_window=20, lookback=60, threshold=0.80)])


def compute_exposure_series(bars: Sequence[Bar], config: ExposureMechanismConfig) -> dict[datetime, float]:
    """output[timestamp] = exposure fraction, ONLY at rebalance-bar
    timestamps (every bar for "daily", every 5th for "weekly") and ONLY
    where every needed feature is already defined (skips the warmup
    period — never guesses). Causal by construction: every feature this
    draws on already proves no-future-data via its own
    tests/test_*_no_lookahead* suite; `compute_exposure_series` itself
    additionally gets its OWN no-lookahead test (mutate-the-future
    methodology) since it adds the rebalance-day subsampling and
    mechanism-dispatch logic on top."""
    engine = _feature_engine()
    frame = engine.compute(bars)
    every_n = REBALANCE_FREQUENCIES[config.rebalance_frequency]
    mechanism_kwargs = {"target_annual_vol": config.target_annual_vol} if config.mechanism == "VOL_TARGET" else {}
    dispatch = _DISPATCH[config.mechanism]

    out: dict[datetime, float] = {}
    for i, ts in enumerate(frame.timestamps):
        if i % every_n != 0:
            continue
        row = {name: frame.columns[name][i] for name in frame.feature_names}
        exposure = dispatch(row, **mechanism_kwargs)
        if exposure is not None:
            out[ts] = exposure
    return out


def shuffled_exposure_series(real_series: Mapping[datetime, float], *, seed: int) -> dict[datetime, float]:
    """Part 26: shuffles WHICH rebalance timestamp gets which exposure
    value (the exact SAME multiset of values, same timestamps, same
    bounds — only the temporal assignment is scrambled). Tests whether
    TIMING matters, not whether the exposure DISTRIBUTION itself matters."""
    keys = sorted(real_series.keys())
    values = [real_series[k] for k in keys]
    rng = random.Random(seed)
    rng.shuffle(values)
    return dict(zip(keys, values))


def random_exposure_series(real_series: Mapping[datetime, float], *, seed: int) -> dict[datetime, float]:
    """Part 25: draws each rebalance-timestamp's exposure independently
    (with replacement) from the empirical distribution of the REAL
    mechanism's own exposure values — preserves the same rebalance
    timestamps, the same average exposure and bounds (by construction,
    since every drawn value came from the real series), and roughly the
    same turnover-generating behavior, while destroying any information
    the real mechanism's specific SEQUENCE carried."""
    keys = sorted(real_series.keys())
    values = list(real_series.values())
    rng = random.Random(seed)
    return {k: rng.choice(values) for k in keys}
