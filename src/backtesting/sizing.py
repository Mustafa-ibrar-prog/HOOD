"""Position sizing (Phase 3, section 11): turns a strategy's directional
Signal into a concrete target share quantity. Sizing decides how big; the
BacktestRiskAdapter (risk_adapter.py) still has the final word on whether
that size is actually allowed — a strategy can never bypass risk review by
sizing itself, since sizing only ever produces a REQUEST.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class PositionSizer(ABC):
    @abstractmethod
    def target_quantity(
        self,
        *,
        signal_strength: float,
        reference_price: float,
        available_cash: float,
        portfolio_equity: float,
        volatility: float | None = None,
    ) -> int:
        """Returns a non-negative target share count for a LONG signal
        (the engine handles FLAT separately by closing any open position —
        sizing is never consulted for an exit). Never raises for a
        computable-but-zero result; returns 0 rather than guessing."""
        raise NotImplementedError


class FixedQuantitySizer(PositionSizer):
    def __init__(self, quantity: int):
        if quantity < 0:
            raise ValueError("quantity must be >= 0")
        self._quantity = quantity

    def target_quantity(self, **kwargs) -> int:
        return self._quantity


class FixedDollarSizer(PositionSizer):
    def __init__(self, dollars: float):
        if dollars < 0:
            raise ValueError("dollars must be >= 0")
        self._dollars = dollars

    def target_quantity(self, *, reference_price: float, **kwargs) -> int:
        if reference_price <= 0:
            return 0
        return int(self._dollars // reference_price)


class PercentOfPortfolioSizer(PositionSizer):
    def __init__(self, pct: float):
        if not 0 <= pct <= 1:
            raise ValueError("pct must be within [0, 1]")
        self._pct = pct

    def target_quantity(self, *, reference_price: float, portfolio_equity: float, **kwargs) -> int:
        if reference_price <= 0:
            return 0
        dollars = portfolio_equity * self._pct
        return int(dollars // reference_price)


class FixedFractionalRiskSizer(PositionSizer):
    """Sizes so that a hit of `stop_distance` (in price units, e.g. an ATR
    multiple) against the position loses at most `risk_fraction` of
    current portfolio equity — the standard "risk a fixed % per trade"
    rule. Requires the caller to supply `stop_distance`; falls back to 0
    (never guesses a stop) if it isn't given or is non-positive."""

    def __init__(self, risk_fraction: float, stop_distance: float):
        if not 0 <= risk_fraction <= 1:
            raise ValueError("risk_fraction must be within [0, 1]")
        if stop_distance <= 0:
            raise ValueError("stop_distance must be > 0")
        self._risk_fraction = risk_fraction
        self._stop_distance = stop_distance

    def target_quantity(self, *, portfolio_equity: float, **kwargs) -> int:
        risk_dollars = portfolio_equity * self._risk_fraction
        return int(risk_dollars // self._stop_distance)


class VolatilityBasedSizer(PositionSizer):
    """Sizes inversely to a supplied `volatility` figure (e.g. a rolling
    stdev or ATR from src.features.volatility) so a more volatile
    instrument gets a proportionally smaller position for the same target
    dollar risk. Falls back to 0 (never guesses a volatility) if
    `volatility` isn't supplied or is non-positive."""

    def __init__(self, target_dollar_volatility: float):
        if target_dollar_volatility < 0:
            raise ValueError("target_dollar_volatility must be >= 0")
        self._target = target_dollar_volatility

    def target_quantity(self, *, reference_price: float, volatility: float | None = None, **kwargs) -> int:
        if volatility is None or volatility <= 0 or reference_price <= 0:
            return 0
        return int(self._target // volatility)
