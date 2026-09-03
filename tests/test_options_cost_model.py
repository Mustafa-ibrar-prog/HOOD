"""Phase 19, Part 10/19 — mark-to-market vs execution-realistic labeling
and explicitly-assumption-only cost sensitivity."""

from __future__ import annotations

import pytest

from src.options.cost_model import (
    COST_SENSITIVITY_ASSUMPTIONS,
    CostAssumption,
    ResearchRealismLabel,
    apply_cost_assumption,
)


def test_realism_labels_are_distinct():
    assert ResearchRealismLabel.MARK_TO_MARKET_HISTORICAL_RESEARCH != ResearchRealismLabel.EXECUTION_REALISTIC_RESEARCH


def test_cost_assumption_label_must_say_assumption():
    with pytest.raises(ValueError):
        CostAssumption("tight spread", spread_pct_of_mid=0.03, slippage_pct=0.01, commission_per_contract=0.65, rationale="x")


def test_cost_assumption_rejects_negative_components():
    with pytest.raises(ValueError):
        CostAssumption("1x ASSUMPTION", spread_pct_of_mid=-0.01, slippage_pct=0.01, commission_per_contract=0.65, rationale="x")


def test_preregistered_assumptions_all_valid():
    assert len(COST_SENSITIVITY_ASSUMPTIONS) == 3
    for a in COST_SENSITIVITY_ASSUMPTIONS:
        assert "ASSUMPTION" in a.label.upper()


def test_apply_cost_assumption_reduces_return():
    assumption = CostAssumption("1x ASSUMPTION", spread_pct_of_mid=0.05, slippage_pct=0.0, commission_per_contract=0.0, rationale="x")
    net = apply_cost_assumption(0.20, entry_price=10.0, assumption=assumption)
    assert net < 0.20
    assert net == pytest.approx(0.20 - 0.10)  # (0.05+0)*2 round trip


def test_apply_cost_assumption_includes_commission():
    assumption = CostAssumption("1x ASSUMPTION", spread_pct_of_mid=0.0, slippage_pct=0.0, commission_per_contract=1.0, rationale="x")
    net = apply_cost_assumption(0.10, entry_price=5.0, assumption=assumption, contract_multiplier=100)
    # notional = 500, commission_fraction = (1*2)/500 = 0.004
    assert net == pytest.approx(0.10 - 0.004)


def test_apply_cost_assumption_rejects_nonpositive_entry_price():
    assumption = CostAssumption("1x ASSUMPTION", spread_pct_of_mid=0.03, slippage_pct=0.01, commission_per_contract=0.65, rationale="x")
    with pytest.raises(ValueError):
        apply_cost_assumption(0.1, entry_price=0.0, assumption=assumption)


def test_increasing_assumption_severity_increases_cost_drag():
    """1x/2x/3x should be monotonically more punishing -- proves the
    preregistered sensitivity ladder is actually ordered, not accidental."""
    results = []
    for a in COST_SENSITIVITY_ASSUMPTIONS:
        results.append(apply_cost_assumption(0.5, entry_price=10.0, assumption=a))
    assert results[0] > results[1] > results[2]
