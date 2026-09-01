"""Tests for Phase 6, section 18's pre-registered pass criteria."""

from __future__ import annotations

from datetime import datetime, timezone

from src.research.pass_criteria import HoldoutPassCriteria, evaluate_pass_criteria


def _evidence(**overrides):
    base = dict(
        trade_count=50, expectancy=10.0, net_pnl_total=500.0, max_drawdown_pct=-5.0, profit_factor=1.5,
        max_symbol_pnl_share_pct=20.0, top_5pct_trades_pnl_share_pct=15.0, viable_at_2x_costs=True,
        viable_under_extra_execution_delay=True, max_year_pnl_share_pct=30.0,
    )
    base.update(overrides)
    return base


def test_all_criteria_pass_on_clean_evidence():
    criteria = HoldoutPassCriteria(pre_registered_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    evaluation = evaluate_pass_criteria(criteria, **_evidence())
    assert evaluation.all_passed is True
    assert evaluation.fraction_passed == 1.0


def test_small_sample_fails_the_trade_count_criterion():
    criteria = HoldoutPassCriteria()
    evaluation = evaluate_pass_criteria(criteria, **_evidence(trade_count=3))
    result = {r.name: r.passed for r in evaluation.results}
    assert result["minimum trade count"] is False
    assert evaluation.all_passed is False


def test_single_symbol_dominance_fails_that_criterion_only():
    criteria = HoldoutPassCriteria()
    evaluation = evaluate_pass_criteria(criteria, **_evidence(max_symbol_pnl_share_pct=80.0))
    result = {r.name: r.passed for r in evaluation.results}
    assert result["no single-symbol dominance"] is False
    assert result["positive expectancy"] is True  # other criteria unaffected


def test_negative_expectancy_fails():
    criteria = HoldoutPassCriteria()
    evaluation = evaluate_pass_criteria(criteria, **_evidence(expectancy=-5.0))
    result = {r.name: r.passed for r in evaluation.results}
    assert result["positive expectancy"] is False


def test_unavailable_drawdown_is_reported_as_not_applicable_not_a_silent_pass():
    criteria = HoldoutPassCriteria()
    evaluation = evaluate_pass_criteria(criteria, **_evidence(max_drawdown_pct=None))
    result = {r.name: r.passed for r in evaluation.results}
    assert result["acceptable max drawdown"] is None
    # N/A criteria don't count as passed, but also shouldn't force
    # all_passed to False on their own if genuinely unavailable
    assert "N/A" in evaluation.render()


def test_render_includes_pass_fail_labels():
    criteria = HoldoutPassCriteria()
    evaluation = evaluate_pass_criteria(criteria, **_evidence(max_symbol_pnl_share_pct=90.0))
    rendered = evaluation.render()
    assert "[FAIL]" in rendered
    assert "[PASS]" in rendered


def test_criteria_round_trip_through_dict():
    criteria = HoldoutPassCriteria(pre_registered_at=datetime(2026, 1, 1, tzinfo=timezone.utc), min_holdout_trade_count=30)
    restored = HoldoutPassCriteria.from_dict(criteria.as_dict())
    assert restored.min_holdout_trade_count == 30
    assert restored.pre_registered_at == criteria.pre_registered_at
