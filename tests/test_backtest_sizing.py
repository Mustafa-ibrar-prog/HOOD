"""Tests for position sizing methods (Phase 3, section 11)."""

from __future__ import annotations

import pytest

from src.backtesting.sizing import (
    FixedDollarSizer,
    FixedFractionalRiskSizer,
    FixedQuantitySizer,
    PercentOfPortfolioSizer,
    VolatilityBasedSizer,
)


def test_fixed_quantity_sizer_always_returns_configured_quantity():
    sizer = FixedQuantitySizer(25)
    assert sizer.target_quantity(signal_strength=1.0, reference_price=50.0, available_cash=1000, portfolio_equity=1000) == 25


def test_fixed_dollar_sizer_divides_by_price():
    sizer = FixedDollarSizer(1000.0)
    assert sizer.target_quantity(signal_strength=1.0, reference_price=45.0, available_cash=2000, portfolio_equity=2000) == 22


def test_fixed_dollar_sizer_zero_on_zero_price():
    sizer = FixedDollarSizer(1000.0)
    assert sizer.target_quantity(signal_strength=1.0, reference_price=0.0, available_cash=2000, portfolio_equity=2000) == 0


def test_percent_of_portfolio_sizer():
    sizer = PercentOfPortfolioSizer(0.10)
    assert sizer.target_quantity(signal_strength=1.0, reference_price=10.0, available_cash=10000, portfolio_equity=10000) == 100


def test_percent_of_portfolio_sizer_rejects_out_of_range():
    with pytest.raises(ValueError):
        PercentOfPortfolioSizer(1.5)


def test_fixed_fractional_risk_sizer():
    sizer = FixedFractionalRiskSizer(risk_fraction=0.02, stop_distance=2.0)
    # Risking 2% of 10,000 = 200; stop distance $2/share -> 100 shares
    assert sizer.target_quantity(signal_strength=1.0, reference_price=50.0, available_cash=10000, portfolio_equity=10000) == 100


def test_volatility_based_sizer_inverse_to_volatility():
    sizer = VolatilityBasedSizer(target_dollar_volatility=1000.0)
    low_vol_qty = sizer.target_quantity(signal_strength=1.0, reference_price=50.0, available_cash=10000, portfolio_equity=10000, volatility=1.0)
    high_vol_qty = sizer.target_quantity(signal_strength=1.0, reference_price=50.0, available_cash=10000, portfolio_equity=10000, volatility=10.0)
    assert low_vol_qty > high_vol_qty


def test_volatility_based_sizer_zero_when_volatility_not_given():
    sizer = VolatilityBasedSizer(target_dollar_volatility=1000.0)
    assert sizer.target_quantity(signal_strength=1.0, reference_price=50.0, available_cash=10000, portfolio_equity=10000, volatility=None) == 0


def test_volatility_based_sizer_zero_when_volatility_non_positive():
    sizer = VolatilityBasedSizer(target_dollar_volatility=1000.0)
    assert sizer.target_quantity(signal_strength=1.0, reference_price=50.0, available_cash=10000, portfolio_equity=10000, volatility=0.0) == 0
