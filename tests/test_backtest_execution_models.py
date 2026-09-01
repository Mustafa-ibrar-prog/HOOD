"""Tests for execution timing, slippage, transaction cost, and spread
models (Phase 3, sections 4-7)."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from src.backtesting.execution_models import (
    BasisPointSlippage,
    CompositeCostModel,
    FixedPercentSlippage,
    FixedPercentSpreadModel,
    NextBarExecutionModel,
    PerShareCommission,
    PercentOfNotionalCommission,
    PerSymbolSlippage,
    SellOnlyFee,
    SizeAwareSlippage,
    VolatilityAdjustedSlippage,
    ZeroCostModel,
    ZeroSlippage,
    apply_slippage,
    spread_adjusted_price,
)
from src.data.bar import Bar


def _bar(**overrides) -> Bar:
    defaults = dict(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), symbol="AAPL", timeframe="day", open=100.0, high=102.0, low=98.0, close=100.0, volume=10_000)
    defaults.update(overrides)
    return Bar(**defaults)


# --- Execution model (section 4) ------------------------------------------------------------


def test_next_bar_execution_model_defaults_to_open_one_bar_later():
    model = NextBarExecutionModel()
    assert model.delay_bars() == 1
    assert model.reference_price(_bar(open=101.5)) == 101.5


def test_next_bar_execution_model_rejects_zero_delay():
    with pytest.raises(ValueError, match="look-ahead"):
        NextBarExecutionModel(delay_bars=0)


def test_next_bar_execution_model_supports_configurable_price_field_and_delay():
    model = NextBarExecutionModel(price_field="close", delay_bars=3)
    assert model.delay_bars() == 3
    assert model.reference_price(_bar(close=99.0)) == 99.0


def test_next_bar_execution_model_rejects_unknown_price_field():
    with pytest.raises(ValueError):
        NextBarExecutionModel(price_field="mid")


# --- Slippage (section 5) -------------------------------------------------------------------


def test_zero_slippage_is_explicit_not_default():
    price = apply_slippage(ZeroSlippage(), reference_price=100.0, side="buy", quantity=10, bar=_bar())
    assert price == 100.0


def test_fixed_percent_slippage_buy_pays_more_sell_receives_less():
    model = FixedPercentSlippage(0.01)
    buy_price = apply_slippage(model, reference_price=100.0, side="buy", quantity=1, bar=_bar())
    sell_price = apply_slippage(model, reference_price=100.0, side="sell", quantity=1, bar=_bar())
    assert buy_price == pytest.approx(101.0)
    assert sell_price == pytest.approx(99.0)


def test_basis_point_slippage_matches_percent_equivalent():
    bps_model = BasisPointSlippage(50)  # 50 bps == 0.5%
    pct_model = FixedPercentSlippage(0.005)
    assert apply_slippage(bps_model, reference_price=200.0, side="buy", quantity=1, bar=_bar()) == pytest.approx(
        apply_slippage(pct_model, reference_price=200.0, side="buy", quantity=1, bar=_bar())
    )


def test_volatility_adjusted_slippage_increases_with_bar_range():
    model = VolatilityAdjustedSlippage(base_bps=5, range_multiplier=1.0)
    tight_bar = _bar(high=100.5, low=99.5, close=100.0)
    wide_bar = _bar(high=110.0, low=90.0, close=100.0)
    tight_amount = model.slippage_amount(reference_price=100.0, side="buy", quantity=1, bar=tight_bar)
    wide_amount = model.slippage_amount(reference_price=100.0, side="buy", quantity=1, bar=wide_bar)
    assert wide_amount > tight_amount


def test_per_symbol_slippage_uses_the_configured_model_for_that_symbol():
    model = PerSymbolSlippage(by_symbol={"AAPL": FixedPercentSlippage(0.02)}, default=FixedPercentSlippage(0.0))
    aapl_amount = model.slippage_amount(reference_price=100.0, side="buy", quantity=1, bar=_bar(symbol="AAPL"))
    other_amount = model.slippage_amount(reference_price=100.0, side="buy", quantity=1, bar=_bar(symbol="SOFI"))
    assert aapl_amount == pytest.approx(2.0)
    assert other_amount == pytest.approx(0.0)


def test_size_aware_slippage_scales_with_participation_rate():
    model = SizeAwareSlippage(FixedPercentSlippage(0.01), participation_multiplier=1.0)
    small_order = model.slippage_amount(reference_price=100.0, side="buy", quantity=10, bar=_bar(volume=10_000))
    large_order = model.slippage_amount(reference_price=100.0, side="buy", quantity=5_000, bar=_bar(volume=10_000))
    assert large_order > small_order


def test_size_aware_slippage_safe_when_bar_volume_is_zero():
    model = SizeAwareSlippage(FixedPercentSlippage(0.01))
    amount = model.slippage_amount(reference_price=100.0, side="buy", quantity=10, bar=_bar(volume=0))
    assert amount == pytest.approx(1.0)  # falls back to the base model, unscaled


def test_slippage_models_reject_negative_parameters():
    with pytest.raises(ValueError):
        FixedPercentSlippage(-0.01)
    with pytest.raises(ValueError):
        BasisPointSlippage(-5)


# --- Transaction costs (section 6) --------------------------------------------------------


def test_zero_cost_model():
    assert ZeroCostModel().compute_fees(side="buy", quantity=100, execution_price=10.0) == 0.0


def test_per_share_commission_respects_minimum():
    model = PerShareCommission(commission_per_share=0.005, minimum=1.0)
    assert model.compute_fees(side="buy", quantity=10, execution_price=100.0) == pytest.approx(1.0)  # 10*0.005=0.05 < minimum
    assert model.compute_fees(side="buy", quantity=1000, execution_price=100.0) == pytest.approx(5.0)


def test_percent_of_notional_commission():
    model = PercentOfNotionalCommission(pct=0.001)
    assert model.compute_fees(side="sell", quantity=100, execution_price=50.0) == pytest.approx(5.0)


def test_composite_cost_model_sums_components():
    model = CompositeCostModel([PerShareCommission(0.01), PercentOfNotionalCommission(0.0001)])
    fee = model.compute_fees(side="buy", quantity=100, execution_price=50.0)
    assert fee == pytest.approx(100 * 0.01 + 100 * 50.0 * 0.0001)


def test_sell_only_fee_is_zero_on_buys():
    model = SellOnlyFee(PercentOfNotionalCommission(0.001))
    assert model.compute_fees(side="buy", quantity=100, execution_price=50.0) == 0.0
    assert model.compute_fees(side="sell", quantity=100, execution_price=50.0) > 0.0


# --- Spread (section 7) --------------------------------------------------------------------


def test_fixed_percent_spread_buy_uses_ask_sell_uses_bid():
    model = FixedPercentSpreadModel(0.01)  # 1% total spread
    bar = _bar()
    buy_price, buy_source = spread_adjusted_price(model, reference_price=100.0, side="buy", bar=bar)
    sell_price, sell_source = spread_adjusted_price(model, reference_price=100.0, side="sell", bar=bar)
    assert buy_price == pytest.approx(100.5)
    assert sell_price == pytest.approx(99.5)
    assert buy_source == "modeled_spread"
    assert sell_source == "modeled_spread"


def test_spread_model_never_silently_labeled_as_real():
    model = FixedPercentSpreadModel(0.0)
    _price, source = spread_adjusted_price(model, reference_price=100.0, side="buy", bar=_bar())
    assert source == "modeled_spread"  # even a zero spread is honestly labeled, not upgraded to "real"
