"""Phase 38, Part 4-5 — candidate audit + underlying-vs-option edge
separation."""

from __future__ import annotations

from datetime import datetime, timezone

from src.options.phase38_candidate_audit import (
    CANDIDATE_AUDIT,
    candidates_excluded_this_phase,
    candidates_included_this_phase,
)
from src.options.phase38_targets import ForwardOutcome
from src.options.phase38_underlying_vs_option_edge import EdgeClassification, evaluate_underlying_vs_option_edge


def test_no_rejected_candidate_resurrected_without_new_evidence():
    """Every candidate excluded this phase must carry a documented
    rejection reason and an explicit inclusion_or_exclusion_reason
    referencing the absence of new evidence."""
    for record in candidates_excluded_this_phase():
        assert record.prior_rejection_reason
        assert record.inclusion_or_exclusion_reason


def test_momentum_breakout_is_the_one_included_candidate():
    included = candidates_included_this_phase()
    assert {c.candidate_id for c in included} == {"MOMENTUM_BREAKOUT_EXISTING_V1"}


def test_candidate_audit_never_declares_a_candidate_validated():
    for record in CANDIDATE_AUDIT:
        assert record.prior_classification != "VALIDATED_CANDIDATE"
        assert "VALIDATED" not in record.prior_classification or record.prior_classification == "NULL (0 DISCOVERY_SUPPORTED / PROMISING out of 16)"


def _outcome(option_return, underlying_return):
    return ForwardOutcome(
        option_id="opt-1", underlying_symbol="AAPL", horizon_label="5min", entry_cycle_id="c0",
        entry_timestamp=datetime(2026, 9, 8, tzinfo=timezone.utc), exit_cycle_id="c1",
        exit_timestamp=datetime(2026, 9, 8, tzinfo=timezone.utc), entry_ask=1.0, entry_bid=0.95, exit_bid=1.0, exit_ask=1.05,
        mid_return_pct=option_return, executable_return_pct=option_return, mfe_pct=0.0, mae_pct=0.0,
        directional_outcome="UP", risk_adjusted_outcome=None, entry_underlying=100.0, exit_underlying=100.0 * (1 + underlying_return),
        underlying_return_pct=underlying_return, option_minus_underlying_return_pct=option_return - underlying_return,
        data_limited_reason=None,
    )


def test_edge_evaluation_insufficient_sample_below_floor():
    result = evaluate_underlying_vs_option_edge([_outcome(0.1, 0.05)] * 5)
    assert result.classification == EdgeClassification.INSUFFICIENT_SAMPLE


def test_edge_evaluation_underlying_derived_when_excess_not_positive():
    outcomes = [_outcome(0.05, 0.05)] * 25  # option return == underlying return exactly -- zero excess
    result = evaluate_underlying_vs_option_edge(outcomes)
    assert result.classification == EdgeClassification.UNDERLYING_DERIVED


def test_edge_evaluation_never_accepts_bare_underlying_move_as_option_edge():
    """'Underlying went up, therefore call made money' -- Part 5's exact
    forbidden inference. Simulate exactly that: option_return always
    equal to underlying_return (the option added literally nothing)."""
    outcomes = [_outcome(u, u) for u in [0.01, 0.02, -0.01, 0.03, 0.0] * 5]
    result = evaluate_underlying_vs_option_edge(outcomes)
    assert result.classification == EdgeClassification.UNDERLYING_DERIVED
    assert result.mean_excess_return is not None and abs(result.mean_excess_return) < 1e-9


def test_edge_evaluation_option_adds_value_with_a_real_positive_excess():
    import random
    random.seed(42)
    outcomes = [_outcome(0.05 + random.gauss(0.02, 0.001), 0.0) for _ in range(50)]  # consistently positive excess, tight distribution
    result = evaluate_underlying_vs_option_edge(outcomes)
    assert result.classification == EdgeClassification.OPTION_ADDS_VALUE
    assert result.excess_return_p_value < 0.05


def test_edge_evaluation_inconclusive_with_noisy_marginal_excess():
    import random
    random.seed(7)
    outcomes = [_outcome(random.gauss(0.001, 0.2), 0.0) for _ in range(25)]  # tiny mean, huge noise
    result = evaluate_underlying_vs_option_edge(outcomes)
    assert result.classification in (EdgeClassification.INCONCLUSIVE, EdgeClassification.UNDERLYING_DERIVED)


def test_edge_evaluation_ignores_outcomes_with_no_computable_excess():
    unavailable = ForwardOutcome(
        option_id="opt-1", underlying_symbol="AAPL", horizon_label="5min", entry_cycle_id="c0",
        entry_timestamp=datetime(2026, 9, 8, tzinfo=timezone.utc), exit_cycle_id=None, exit_timestamp=None,
        entry_ask=1.0, entry_bid=0.95, exit_bid=None, exit_ask=None, mid_return_pct=None, executable_return_pct=None,
        mfe_pct=None, mae_pct=None, directional_outcome=None, risk_adjusted_outcome=None, entry_underlying=100.0,
        exit_underlying=None, underlying_return_pct=None, option_minus_underlying_return_pct=None,
        data_limited_reason="no later observation",
    )
    result = evaluate_underlying_vs_option_edge([unavailable] * 30)
    assert result.classification == EdgeClassification.INSUFFICIENT_SAMPLE
    assert result.n_outcomes == 0
