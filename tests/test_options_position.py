"""Phase 18, Part 22/11 — options position and multi-leg representation
tests, including the risk-profile "do not assume linear payoff"
requirement."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.options.instrument import OptionContract
from src.options.position import OptionLegPosition, OptionsPosition, analyze_position_risk

LONG_CALL = OptionContract(underlying_symbol="AAPL", option_id="c55a630e", call_put="call", strike=175.0, expiration=date(2022, 1, 21))
SHORT_CALL_180 = OptionContract(underlying_symbol="AAPL", option_id="hyp-180c", call_put="call", strike=180.0, expiration=date(2022, 1, 21))


def _leg(contract=LONG_CALL, side="long", quantity=1, entry_price=3.53) -> OptionLegPosition:
    return OptionLegPosition(contract=contract, side=side, quantity=quantity, entry_price=entry_price, entry_timestamp=datetime(2021, 12, 1, tzinfo=timezone.utc))


def test_invalid_side_rejected():
    with pytest.raises(ValueError):
        _leg(side="both")


def test_invalid_quantity_rejected():
    with pytest.raises(ValueError):
        _leg(quantity=0)


def test_negative_entry_price_rejected():
    with pytest.raises(ValueError):
        _leg(entry_price=-1.0)


def test_long_leg_entry_cashflow_is_negative_debit():
    leg = _leg(side="long", entry_price=3.53, quantity=1)
    assert leg.entry_cashflow == -353.0


def test_short_leg_entry_cashflow_is_positive_credit():
    leg = _leg(side="short", entry_price=3.53, quantity=1)
    assert leg.entry_cashflow == 353.0


def test_position_requires_at_least_one_leg():
    with pytest.raises(ValueError):
        OptionsPosition(legs=(), opened_at=datetime(2021, 12, 1, tzinfo=timezone.utc))


def test_is_single_leg():
    pos = OptionsPosition(legs=(_leg(),), opened_at=datetime(2021, 12, 1, tzinfo=timezone.utc))
    assert pos.is_single_leg is True


def test_unrealized_pnl_none_when_mark_missing():
    pos = OptionsPosition(legs=(_leg(),), opened_at=datetime(2021, 12, 1, tzinfo=timezone.utc))
    assert pos.unrealized_pnl({}) is None  # missing mark for the one leg


def test_unrealized_pnl_computed_when_mark_present():
    pos = OptionsPosition(legs=(_leg(side="long", entry_price=3.53),), opened_at=datetime(2021, 12, 1, tzinfo=timezone.utc))
    pnl = pos.unrealized_pnl({LONG_CALL.option_id: 5.00})
    assert pnl == pytest.approx((5.00 - 3.53) * 100)


# --- risk profile: single leg -------------------------------------------------------------------


def test_long_call_risk():
    pos = OptionsPosition(legs=(_leg(side="long", entry_price=3.53),), opened_at=datetime(2021, 12, 1, tzinfo=timezone.utc))
    risk = analyze_position_risk(pos)
    assert risk.max_loss == 353.0
    assert risk.max_profit is None  # unbounded
    assert risk.is_defined_risk is True


def test_long_put_risk():
    put = OptionContract(underlying_symbol="AAPL", option_id="p1", call_put="put", strike=25.0, expiration=date(2022, 1, 21))
    pos = OptionsPosition(legs=(_leg(contract=put, side="long", entry_price=0.01),), opened_at=datetime(2021, 12, 1, tzinfo=timezone.utc))
    risk = analyze_position_risk(pos)
    assert risk.max_loss == 1.0  # 0.01 * 100
    assert risk.max_profit == 25 * 100 - 1.0
    assert risk.is_defined_risk is True


def test_short_call_naked_risk_undefined():
    pos = OptionsPosition(legs=(_leg(side="short", entry_price=3.53),), opened_at=datetime(2021, 12, 1, tzinfo=timezone.utc))
    risk = analyze_position_risk(pos)
    assert risk.max_loss is None  # unbounded
    assert risk.max_profit == 353.0
    assert risk.is_defined_risk is False


def test_short_put_cash_secured_risk():
    put = OptionContract(underlying_symbol="AAPL", option_id="p1", call_put="put", strike=25.0, expiration=date(2022, 1, 21))
    pos = OptionsPosition(legs=(_leg(contract=put, side="short", entry_price=0.05),), opened_at=datetime(2021, 12, 1, tzinfo=timezone.utc))
    risk = analyze_position_risk(pos)
    assert risk.max_loss == 25 * 100 - 5.0
    assert risk.max_profit == 5.0
    assert risk.is_defined_risk is True


# --- risk profile: 2-leg vertical spread ----------------------------------------------------------


def test_bull_call_spread_net_debit_risk():
    long_leg = _leg(contract=LONG_CALL, side="long", entry_price=3.53)
    short_leg = _leg(contract=SHORT_CALL_180, side="short", entry_price=1.80)
    pos = OptionsPosition(legs=(long_leg, short_leg), opened_at=datetime(2021, 12, 1, tzinfo=timezone.utc))
    risk = analyze_position_risk(pos)
    width = (180.0 - 175.0) * 100
    debit = (3.53 - 1.80) * 100
    assert risk.max_loss == pytest.approx(debit)
    assert risk.max_profit == pytest.approx(width - debit)
    assert risk.is_defined_risk is True


def test_bear_call_spread_net_credit_risk():
    long_leg = _leg(contract=LONG_CALL, side="short", entry_price=3.53)  # short the lower strike
    short_leg = _leg(contract=SHORT_CALL_180, side="long", entry_price=1.80)  # long the higher strike
    pos = OptionsPosition(legs=(long_leg, short_leg), opened_at=datetime(2021, 12, 1, tzinfo=timezone.utc))
    risk = analyze_position_risk(pos)
    width = (180.0 - 175.0) * 100
    credit = (3.53 - 1.80) * 100
    assert risk.max_profit == pytest.approx(credit)
    assert risk.max_loss == pytest.approx(width - credit)


def test_mismatched_expiration_two_leg_falls_through_to_unsupported():
    other_month = OptionContract(underlying_symbol="AAPL", option_id="hyp-feb-180c", call_put="call", strike=180.0, expiration=date(2022, 2, 18))
    pos = OptionsPosition(legs=(_leg(contract=LONG_CALL, side="long"), _leg(contract=other_month, side="short", entry_price=1.80)), opened_at=datetime(2021, 12, 1, tzinfo=timezone.utc))
    risk = analyze_position_risk(pos)
    assert risk.max_loss is None
    assert risk.max_profit is None
    assert "UNSUPPORTED_STRUCTURE" in risk.method


def test_three_or_more_legs_unsupported():
    third = OptionContract(underlying_symbol="AAPL", option_id="hyp-185c", call_put="call", strike=185.0, expiration=date(2022, 1, 21))
    pos = OptionsPosition(
        legs=(_leg(contract=LONG_CALL, side="long"), _leg(contract=SHORT_CALL_180, side="short", entry_price=1.80), _leg(contract=third, side="long", entry_price=0.90)),
        opened_at=datetime(2021, 12, 1, tzinfo=timezone.utc),
    )
    risk = analyze_position_risk(pos)
    assert risk.max_loss is None
    assert risk.max_profit is None
    assert "UNSUPPORTED_STRUCTURE" in risk.method


def test_strategy_label_does_not_drive_risk_logic():
    """A deliberately WRONG label must not change the computed result --
    analyze_position_risk inspects the legs, never the label."""
    pos = OptionsPosition(legs=(_leg(side="long", entry_price=3.53),), opened_at=datetime(2021, 12, 1, tzinfo=timezone.utc), strategy_label="totally_wrong_label")
    risk = analyze_position_risk(pos)
    assert risk.max_loss == 353.0


def test_underlying_symbols_property():
    pos = OptionsPosition(legs=(_leg(contract=LONG_CALL), _leg(contract=SHORT_CALL_180, side="short", entry_price=1.80)), opened_at=datetime(2021, 12, 1, tzinfo=timezone.utc))
    assert pos.underlying_symbols == ("AAPL",)
