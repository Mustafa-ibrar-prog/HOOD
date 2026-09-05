"""Phase 35, Part M — the strategy gate classification."""

from __future__ import annotations

from src.options.phase35_strategy_gate import StrategyClassification, StrategyGateEvidence, classify_strategy


def _evidence(**overrides):
    base = dict(
        n_trades=50, mean_net_pnl=10.0, bootstrap_excludes_zero_90pct=True,
        cost_survives_1x=True, cost_survives_2x=True, cost_survives_3x=True, cost_survives_5x=True,
        placebo_empirical_p=0.02, outlier_dependent=False, leave_one_symbol_out_all_positive=True,
        leave_one_period_out_all_positive=True, pct_trades_affordable_1000usd=0.9,
        underlying_only_edge_present=False, option_adds_value_after_costs=True,
    )
    base.update(overrides)
    return StrategyGateEvidence(**base)


def test_not_ready_below_minimum_sample():
    result, reason, criteria = classify_strategy(_evidence(n_trades=5))
    assert result is StrategyClassification.NOT_READY


def test_inherited_from_underlying_when_option_adds_no_value():
    result, reason, criteria = classify_strategy(_evidence(underlying_only_edge_present=True, option_adds_value_after_costs=False))
    assert result is StrategyClassification.INHERITED_FROM_UNDERLYING


def test_rejected_on_negative_expectancy():
    result, reason, criteria = classify_strategy(_evidence(mean_net_pnl=-5.0))
    assert result is StrategyClassification.REJECTED


def test_rejected_when_fails_baseline_cost():
    result, reason, criteria = classify_strategy(_evidence(cost_survives_1x=False))
    assert result is StrategyClassification.REJECTED


def test_validated_candidate_when_everything_passes():
    result, reason, criteria = classify_strategy(_evidence())
    assert result is StrategyClassification.VALIDATED_CANDIDATE
    assert all(c.passed is not False for c in criteria)


def test_promising_when_bootstrap_ok_but_fails_5x_cost():
    result, reason, criteria = classify_strategy(_evidence(cost_survives_5x=False))
    assert result is StrategyClassification.PROMISING


def test_fragile_when_outlier_dependent():
    result, reason, criteria = classify_strategy(_evidence(outlier_dependent=True))
    assert result is StrategyClassification.TRADEABLE_SIGNAL_FRAGILE


def test_fragile_when_fails_affordability():
    result, reason, criteria = classify_strategy(_evidence(pct_trades_affordable_1000usd=0.1))
    assert result is StrategyClassification.TRADEABLE_SIGNAL_FRAGILE


def test_fragile_when_fails_leave_one_out():
    result, reason, criteria = classify_strategy(_evidence(leave_one_symbol_out_all_positive=False))
    assert result is StrategyClassification.TRADEABLE_SIGNAL_FRAGILE


def test_inconclusive_when_bootstrap_does_not_exclude_zero():
    result, reason, criteria = classify_strategy(_evidence(bootstrap_excludes_zero_90pct=False))
    assert result is StrategyClassification.INCONCLUSIVE


def test_never_invents_a_new_category():
    seen = set()
    for kwargs in (
        {}, {"n_trades": 5}, {"mean_net_pnl": -1.0}, {"outlier_dependent": True},
        {"bootstrap_excludes_zero_90pct": False}, {"cost_survives_5x": False},
        {"underlying_only_edge_present": True, "option_adds_value_after_costs": False},
    ):
        result, _, _ = classify_strategy(_evidence(**kwargs))
        seen.add(result)
    assert seen <= set(StrategyClassification)
