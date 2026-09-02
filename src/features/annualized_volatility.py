"""Phase 11, Part 5-6: a thin, name-stable wrapper around the unmodified
Phase 2 RealizedVolatility(window, annualization_factor=...) — exists
ONLY so an ANNUALIZED volatility forecast (needed to compare directly
against a target_annual_vol like 15%) gets its OWN, unambiguous column
name, distinct from every prior phase's non-annualized
"realized_vol_{window}" convention (Phase 9/10's discovery panels use the
RAW, non-annualized reading throughout). Mixing the two under the same
name in the same feature set would be a silent units bug — see Phase 10's
own postmortem on exactly this kind of mismatch
(src/research/phase10_targets.py's future_volatility_change fix).

Delegates entirely to RealizedVolatility — no reimplementation.
"""

from __future__ import annotations

from typing import Sequence

from src.data.bar import Bar
from src.features.base import Feature, FeatureSpec
from src.features.volatility import RealizedVolatility

TRADING_DAYS_PER_YEAR = 252.0


class AnnualizedRealizedVolatility(Feature):
    """sqrt(252) * RealizedVolatility(window) — an ANNUALIZED realized
    volatility forecast, directly comparable to an annualized
    target_volatility (e.g. 0.15 for 15%)."""

    def __init__(self, window: int = 20):
        if window < 2:
            raise ValueError("window must be >= 2")
        self.window = window
        self._rv = RealizedVolatility(window, annualization_factor=TRADING_DAYS_PER_YEAR)
        self.spec = FeatureSpec(
            name=f"realized_vol_{window}_ann", version="1.0", params={"window": window, "annualization_factor": TRADING_DAYS_PER_YEAR},
            required_columns=("close",), lookback=window,
            description=f"ANNUALIZED rolling stdev of log returns over {window} bars (sqrt({TRADING_DAYS_PER_YEAR:.0f})-scaled)",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        return self._rv.compute(bars)
