"""Phase 36, Part 12-13 — the Opportunity -> Risk -> PositionSizer ->
ExecutionOrder handoff, and opportunity ranking."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest

from src.backtesting.sizing import FixedQuantitySizer
from src.production.decision import DecisionType, StrategyDecision
from src.production.liquidity import LiquidityClassification, assess_liquidity
from src.production.live_snapshot import OptionLiveState
from src.production.opportunity import build_opportunity
from src.production.ranking import NO_VALIDATED_STRATEGY, rank_opportunities, rank_or_no_validated_strategy
from src.production.risk_handoff import evaluate_opportunity_against_risk
from src.production.snapshot import AccountState
from src.risk.manager import RiskManager
from src.risk.models import RiskLimits


def _now():
    return datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc)


def _limits(**overrides) -> RiskLimits:
    defaults = dict(
        max_trades_per_day=4, max_daily_loss_usd=200.0, max_position_size_usd=250.0,
        cooldown_minutes_after_exit=15, stale_data_max_seconds=90.0, max_spread_pct=0.10,
        min_option_volume=50, min_option_open_interest=100, max_extended_move_pct=0.25,
        entry_cutoff_time=time(15, 30),
    )
    defaults.update(overrides)
    return RiskLimits(**defaults)


def _option(**overrides) -> OptionLiveState:
    defaults = dict(
        option_id="opt-1", underlying="AAPL", option_type="call", strike=230.0,
        expiration=date(2026, 10, 1), dte_days=26, bid=1.0, ask=1.05, bid_size=None, ask_size=None,
        mark=1.02, volume=100, open_interest=200, implied_volatility=None, delta=None, gamma=None,
        theta=None, vega=None, rho=None, state="active", tradability="tradable", timestamp=_now(),
    )
    defaults.update(overrides)
    return OptionLiveState(**defaults)


def _opportunity(**decision_overrides):
    fields = dict(
        strategy_id="X", timestamp=_now(), decision=DecisionType.ENTER, underlying="AAPL",
        option_id="opt-1", side="long_call", quantity_recommendation=1, signal_score=0.8, confidence=0.7,
    )
    fields.update(decision_overrides)
    decision = StrategyDecision(**fields)
    liquidity = assess_liquidity(_option(), now=_now(), risk_limits=_limits())
    return build_opportunity(decision, option=_option(), liquidity=liquidity)


# --- Risk handoff ------------------------------------------------------------------------------


def test_risk_approved_opportunity_produces_an_order_request():
    opp = _opportunity()
    result = evaluate_opportunity_against_risk(
        opp, risk_manager=RiskManager(_limits()), sizer=FixedQuantitySizer(1), account_number="ACC1",
        trades_opened_today=0, daily_pnl_usd=0.0, open_positions=(), last_exit_time=None, data_age_seconds=1.0,
        underlying_move_pct=0.0, now=_now(), last_position_size_usd=None, last_trade_was_loss=False,
        available_cash=1000.0, portfolio_equity=1000.0,
    )
    assert result.order_request is not None
    assert result.order_request.legs[0].option_id == "opt-1"
    assert result.order_request.quantity == "1"
    assert result.rejection_reason is None


def test_risk_rejected_opportunity_produces_no_order():
    opp = _opportunity()
    result = evaluate_opportunity_against_risk(
        opp, risk_manager=RiskManager(_limits(max_trades_per_day=0)), sizer=FixedQuantitySizer(1), account_number="ACC1",
        trades_opened_today=5, daily_pnl_usd=0.0, open_positions=(), last_exit_time=None, data_age_seconds=1.0,
        underlying_move_pct=0.0, now=_now(), last_position_size_usd=None, last_trade_was_loss=False,
        available_cash=1000.0, portfolio_equity=1000.0,
    )
    assert result.order_request is None
    assert result.rejection_reason is not None


def test_zero_sized_quantity_produces_no_order():
    opp = _opportunity()
    result = evaluate_opportunity_against_risk(
        opp, risk_manager=RiskManager(_limits()), sizer=FixedQuantitySizer(0), account_number="ACC1",
        trades_opened_today=0, daily_pnl_usd=0.0, open_positions=(), last_exit_time=None, data_age_seconds=1.0,
        underlying_move_pct=0.0, now=_now(), last_position_size_usd=None, last_trade_was_loss=False,
        available_cash=1000.0, portfolio_equity=1000.0,
    )
    assert result.order_request is None
    assert "zero" in result.rejection_reason.lower()


def test_strategy_quantity_recommendation_never_becomes_the_final_order_quantity():
    """Part 12: 'Strategy cannot override risk.' The strategy asked for 1
    contract; the sizer is configured to size 3 -- the final order must
    reflect the SIZER's number, not the strategy's hint."""
    opp = _opportunity()
    result = evaluate_opportunity_against_risk(
        opp, risk_manager=RiskManager(_limits(max_position_size_usd=10_000.0)), sizer=FixedQuantitySizer(3),
        account_number="ACC1", trades_opened_today=0, daily_pnl_usd=0.0, open_positions=(), last_exit_time=None,
        data_age_seconds=1.0, underlying_move_pct=0.0, now=_now(), last_position_size_usd=None,
        last_trade_was_loss=False, available_cash=1000.0, portfolio_equity=1000.0,
    )
    assert result.order_request.quantity == "3"
    assert opp.decision.quantity_recommendation == 1  # the strategy's own hint, unchanged


def test_missing_entry_price_never_evaluated_against_risk():
    decision = StrategyDecision(
        strategy_id="X", timestamp=_now(), decision=DecisionType.ENTER, underlying="AAPL",
        option_id="opt-1", side="long_call", quantity_recommendation=1,
    )
    liquidity = assess_liquidity(_option(ask=None, bid=None), now=_now(), risk_limits=_limits())
    opp = build_opportunity(decision, option=_option(ask=None, bid=None), liquidity=liquidity)
    result = evaluate_opportunity_against_risk(
        opp, risk_manager=RiskManager(_limits()), sizer=FixedQuantitySizer(1), account_number="ACC1",
        trades_opened_today=0, daily_pnl_usd=0.0, open_positions=(), last_exit_time=None, data_age_seconds=1.0,
        underlying_move_pct=0.0, now=_now(), last_position_size_usd=None, last_trade_was_loss=False,
        available_cash=1000.0, portfolio_equity=1000.0,
    )
    assert result.order_request is None
    assert result.risk_decision is None  # never even reached RiskManager


# --- Ranking ------------------------------------------------------------------------------------


def _account(buying_power=1000.0, equity=1000.0):
    return AccountState(account_number="ACC1", buying_power_usd=buying_power, equity_usd=equity, as_of=_now())


def test_higher_signal_score_ranks_first():
    strong = _opportunity(signal_score=0.9)
    weak = _opportunity(signal_score=0.1)
    ranked = rank_opportunities([weak, strong], account=_account())
    assert ranked[0].opportunity is strong


def test_concentration_penalty_deprioritizes_already_held_underlying():
    opp = _opportunity()
    ranked_without = rank_opportunities([opp], account=_account())
    ranked_with = rank_opportunities([opp], account=_account(), held_underlyings=frozenset({"AAPL"}))
    assert ranked_with[0].composite_score < ranked_without[0].composite_score
    assert ranked_with[0].concentration_penalty_applied


def test_affordability_penalty_when_max_loss_exceeds_buying_power():
    opp = _opportunity(quantity_recommendation=100)  # 100 contracts * ~$1.05 * 100 multiplier >> $1000
    ranked = rank_opportunities([opp], account=_account(buying_power=100.0))
    assert ranked[0].affordability_penalty_applied


def test_no_validated_strategy_returns_sentinel_not_a_list():
    result = rank_or_no_validated_strategy([_opportunity()], has_validated_strategy=False, account=_account())
    assert result == NO_VALIDATED_STRATEGY


def test_validated_strategy_with_opportunities_returns_ranked_list():
    result = rank_or_no_validated_strategy([_opportunity()], has_validated_strategy=True, account=_account())
    assert isinstance(result, list) and len(result) == 1
