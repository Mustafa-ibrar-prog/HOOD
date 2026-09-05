"""Phase 36, Part 2 — StrategyDecision structural validation."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.production.decision import DecisionType, MalformedDecisionError, StrategyDecision


def _now():
    return datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc)


def test_no_trade_decision_needs_no_contract_fields():
    d = StrategyDecision(strategy_id="X", timestamp=_now(), decision=DecisionType.NO_TRADE, reason="nothing found")
    assert d.underlying is None and d.option_id is None


def test_enter_requires_underlying_option_id_side_and_quantity():
    with pytest.raises(MalformedDecisionError):
        StrategyDecision(strategy_id="X", timestamp=_now(), decision=DecisionType.ENTER)


def test_enter_with_all_required_fields_succeeds():
    d = StrategyDecision(
        strategy_id="X", timestamp=_now(), decision=DecisionType.ENTER, underlying="AAPL",
        option_id="opt-1", side="long_call", quantity_recommendation=1, expiration=date(2026, 10, 1),
    )
    assert d.decision == DecisionType.ENTER


def test_exit_requires_underlying_and_option_id():
    with pytest.raises(MalformedDecisionError):
        StrategyDecision(strategy_id="X", timestamp=_now(), decision=DecisionType.EXIT)
    d = StrategyDecision(strategy_id="X", timestamp=_now(), decision=DecisionType.EXIT, underlying="AAPL", option_id="opt-1")
    assert d.decision == DecisionType.EXIT


def test_hold_cannot_carry_a_quantity_recommendation():
    with pytest.raises(MalformedDecisionError):
        StrategyDecision(strategy_id="X", timestamp=_now(), decision=DecisionType.HOLD, quantity_recommendation=1)


def test_invalid_option_type_rejected():
    with pytest.raises(MalformedDecisionError):
        StrategyDecision(strategy_id="X", timestamp=_now(), decision=DecisionType.NO_TRADE, option_type="stock")


def test_invalid_side_rejected():
    with pytest.raises(MalformedDecisionError):
        StrategyDecision(strategy_id="X", timestamp=_now(), decision=DecisionType.NO_TRADE, side="short_call")


def test_confidence_out_of_range_rejected():
    with pytest.raises(MalformedDecisionError):
        StrategyDecision(strategy_id="X", timestamp=_now(), decision=DecisionType.NO_TRADE, confidence=1.5)


def test_zero_quantity_recommendation_rejected():
    with pytest.raises(MalformedDecisionError):
        StrategyDecision(
            strategy_id="X", timestamp=_now(), decision=DecisionType.ENTER, underlying="AAPL",
            option_id="opt-1", side="long_call", quantity_recommendation=0,
        )


def test_decision_object_has_no_submit_method():
    d = StrategyDecision(strategy_id="X", timestamp=_now(), decision=DecisionType.NO_TRADE)
    assert not hasattr(d, "submit")
    assert not hasattr(d, "place_order")
    assert not hasattr(d, "to_order_request")
