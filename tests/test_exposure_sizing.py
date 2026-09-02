"""Phase 11: EqualWeightExposureSizer tests — hand-computed target
quantities."""

from __future__ import annotations

from src.research.exposure_sizing import EqualWeightExposureSizer


def test_full_exposure_single_symbol():
    sizer = EqualWeightExposureSizer(n_symbols=1)
    qty = sizer.target_quantity(signal_strength=1.0, reference_price=100.0, portfolio_equity=100_000.0)
    assert qty == 1000  # 100% of 100k / $100 = 1000 shares


def test_half_exposure_single_symbol():
    sizer = EqualWeightExposureSizer(n_symbols=1)
    qty = sizer.target_quantity(signal_strength=0.5, reference_price=100.0, portfolio_equity=100_000.0)
    assert qty == 500


def test_equal_weight_across_n_symbols():
    sizer = EqualWeightExposureSizer(n_symbols=20)
    qty = sizer.target_quantity(signal_strength=1.0, reference_price=50.0, portfolio_equity=100_000.0)
    # 100k / 20 symbols = 5000 per symbol; 5000 / 50 = 100 shares
    assert qty == 100


def test_reduced_exposure_scales_down_equal_weight_allocation():
    sizer = EqualWeightExposureSizer(n_symbols=20)
    qty = sizer.target_quantity(signal_strength=0.25, reference_price=50.0, portfolio_equity=100_000.0)
    assert qty == 25  # 0.25 * 5000 / 50


def test_zero_price_returns_zero_not_a_crash():
    sizer = EqualWeightExposureSizer(n_symbols=5)
    assert sizer.target_quantity(signal_strength=1.0, reference_price=0.0, portfolio_equity=100_000.0) == 0


def test_zero_exposure_returns_zero_quantity():
    sizer = EqualWeightExposureSizer(n_symbols=1)
    assert sizer.target_quantity(signal_strength=0.0, reference_price=100.0, portfolio_equity=100_000.0) == 0


def test_invalid_n_symbols_rejected():
    import pytest

    with pytest.raises(ValueError):
        EqualWeightExposureSizer(n_symbols=0)
