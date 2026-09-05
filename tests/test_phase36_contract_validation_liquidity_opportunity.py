"""Phase 36, Part 9-11 — contract validation, liquidity assessment, and
the Opportunity object."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from src.production.contract_validation import ContractRejectionCode, validate_option_contract
from src.production.decision import DecisionType, StrategyDecision
from src.production.liquidity import LiquidityClassification, assess_liquidity
from src.production.live_snapshot import OptionLiveState
from src.production.opportunity import NotAnEntryDecisionError, build_opportunity
from src.risk.models import RiskLimits


def _now():
    return datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc)


def _limits() -> RiskLimits:
    return RiskLimits(
        max_trades_per_day=4, max_daily_loss_usd=200.0, max_position_size_usd=250.0,
        cooldown_minutes_after_exit=15, stale_data_max_seconds=90.0, max_spread_pct=0.10,
        min_option_volume=50, min_option_open_interest=100, max_extended_move_pct=0.25,
        entry_cutoff_time=time(15, 30),
    )


def _option(**overrides) -> OptionLiveState:
    defaults = dict(
        option_id="opt-1", underlying="AAPL", option_type="call", strike=230.0,
        expiration=date(2026, 10, 1), dte_days=26, bid=1.0, ask=1.05, bid_size=None, ask_size=None,
        mark=1.02, volume=100, open_interest=200, implied_volatility=None, delta=None, gamma=None,
        theta=None, vega=None, rho=None, state="active", tradability="tradable", timestamp=_now(),
    )
    defaults.update(overrides)
    return OptionLiveState(**defaults)


# --- Contract validation -----------------------------------------------------------------------


def test_valid_contract_passes():
    result = validate_option_contract(_option(), now=_now(), max_quote_age_seconds=90.0)
    assert result.passed


def test_missing_option_rejected():
    result = validate_option_contract(None, now=_now(), max_quote_age_seconds=90.0)
    assert not result.passed and result.rejection_code == ContractRejectionCode.MISSING_OPTION_ID


def test_missing_option_id_rejected():
    result = validate_option_contract(_option(option_id=""), now=_now(), max_quote_age_seconds=90.0)
    assert result.rejection_code == ContractRejectionCode.MISSING_OPTION_ID


def test_expired_contract_rejected():
    result = validate_option_contract(_option(expiration=date(2020, 1, 1)), now=_now(), max_quote_age_seconds=90.0)
    assert result.rejection_code == ContractRejectionCode.EXPIRED


def test_inactive_contract_rejected():
    result = validate_option_contract(_option(state="inactive"), now=_now(), max_quote_age_seconds=90.0)
    assert result.rejection_code == ContractRejectionCode.INACTIVE


def test_not_tradable_contract_rejected():
    result = validate_option_contract(_option(tradability="untradable"), now=_now(), max_quote_age_seconds=90.0)
    assert result.rejection_code == ContractRejectionCode.NOT_TRADABLE


def test_stale_quote_rejected():
    stale_time = _now() - timedelta(seconds=200)
    result = validate_option_contract(_option(timestamp=stale_time), now=_now(), max_quote_age_seconds=90.0)
    assert result.rejection_code == ContractRejectionCode.STALE_QUOTE


def test_missing_quote_timestamp_rejected():
    result = validate_option_contract(_option(timestamp=None), now=_now(), max_quote_age_seconds=90.0)
    assert result.rejection_code == ContractRejectionCode.CONTRACT_NOT_FOUND


def test_missing_bid_ask_rejected():
    result = validate_option_contract(_option(bid=None, ask=None), now=_now(), max_quote_age_seconds=90.0)
    assert result.rejection_code == ContractRejectionCode.INVALID_PRICE


def test_crossed_market_rejected():
    result = validate_option_contract(_option(bid=1.10, ask=1.00), now=_now(), max_quote_age_seconds=90.0)
    assert result.rejection_code == ContractRejectionCode.ZERO_OR_CROSSED_MARKET


def test_zero_market_rejected():
    result = validate_option_contract(_option(bid=0.0, ask=0.0), now=_now(), max_quote_age_seconds=90.0)
    assert result.rejection_code == ContractRejectionCode.ZERO_OR_CROSSED_MARKET


def test_never_invents_a_price_field_on_rejection():
    result = validate_option_contract(_option(bid=None, ask=None), now=_now(), max_quote_age_seconds=90.0)
    assert "1.0" not in result.message and "invented" not in result.message.lower()


# --- Liquidity assessment ----------------------------------------------------------------------


def test_liquid_contract_classified_liquid():
    assessment = assess_liquidity(_option(), now=_now(), risk_limits=_limits())
    assert assessment.classification == LiquidityClassification.LIQUID


def test_wide_spread_lowers_classification():
    assessment = assess_liquidity(_option(bid=1.0, ask=1.50), now=_now(), risk_limits=_limits())
    assert assessment.classification in (LiquidityClassification.MARGINAL, LiquidityClassification.ILLIQUID)


def test_missing_volume_open_interest_is_unknown_not_liquid():
    assessment = assess_liquidity(_option(volume=None, open_interest=None), now=_now(), risk_limits=_limits())
    assert assessment.classification == LiquidityClassification.UNKNOWN


def test_bid_ask_size_always_configuration_required():
    assessment = assess_liquidity(_option(), now=_now(), risk_limits=_limits())
    assert "min_bid_size" in assessment.configuration_required
    assert "min_ask_size" in assessment.configuration_required


def test_low_volume_and_wide_spread_is_illiquid():
    assessment = assess_liquidity(_option(volume=1, open_interest=1, bid=1.0, ask=2.0), now=_now(), risk_limits=_limits())
    assert assessment.classification == LiquidityClassification.ILLIQUID


# --- Opportunity -----------------------------------------------------------------------------


def test_build_opportunity_requires_enter_decision():
    decision = StrategyDecision(strategy_id="X", timestamp=_now(), decision=DecisionType.NO_TRADE)
    liquidity = assess_liquidity(_option(), now=_now(), risk_limits=_limits())
    with pytest.raises(NotAnEntryDecisionError):
        build_opportunity(decision, option=_option(), liquidity=liquidity)


def test_build_opportunity_estimates_entry_price_and_max_loss():
    decision = StrategyDecision(
        strategy_id="X", timestamp=_now(), decision=DecisionType.ENTER, underlying="AAPL",
        option_id="opt-1", side="long_call", quantity_recommendation=1,
    )
    liquidity = assess_liquidity(_option(), now=_now(), risk_limits=_limits())
    opp = build_opportunity(decision, option=_option(), liquidity=liquidity)
    assert opp.estimated_entry_price == 1.05
    assert opp.estimated_maximum_loss_usd == 1.05 * 1 * 100
