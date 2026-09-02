"""Phase 11: a PositionSizer (src.backtesting.sizing, unmodified — new
subclass, not a modification) that turns a Signal's `strength` (which
Phase 11's strategy uses to carry the EXPOSURE FRACTION, not a directional
confidence score) into an equal-weight target share count.

target_dollars = portfolio_equity * exposure_fraction / n_symbols

This is the ONLY place `signal_strength` gets consulted by a sizer in
this codebase's whole PositionSizer family so far (every prior sizer
ignores it, per src/backtesting/sizing.py's own docstrings) — Phase 11 is
the first phase whose strategy meaningfully uses it.
"""

from __future__ import annotations

from src.backtesting.sizing import PositionSizer


class EqualWeightExposureSizer(PositionSizer):
    def __init__(self, n_symbols: int):
        if n_symbols < 1:
            raise ValueError("n_symbols must be >= 1")
        self._n = n_symbols

    def target_quantity(self, *, signal_strength: float, reference_price: float, portfolio_equity: float, **kwargs) -> int:
        if reference_price <= 0:
            return 0
        dollars = portfolio_equity * signal_strength / self._n
        return max(0, int(dollars // reference_price))
