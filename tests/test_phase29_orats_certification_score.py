"""Phase 29, Part 13/17 — ORATS certification score: structural
correctness, the critical-blocker override (exercised via a synthetic
non-disqualifying case, not just the real disqualified result), and the
real, current ORATS_CERTIFICATION/ORATS_GATE."""

from __future__ import annotations

import pytest

from src.options.orats_certification_score import (
    CRITICAL_BLOCKER_DIMENSIONS,
    ORATS_CERTIFICATION,
    ORATS_GATE,
    ORATSCertificationDimension,
    ORATSCertificationResult,
    ORATSDimensionScore,
    evaluate_orats_gate,
)
from src.options.phase26_final_gate import ResearchReadinessGate


def _all_dims_scored(overrides: dict) -> tuple:
    return tuple(ORATSDimensionScore(d, overrides.get(d, 3), "r") for d in ORATSCertificationDimension)


def test_exactly_fifteen_dimensions():
    assert len(ORATSCertificationDimension) == 15


def test_score_out_of_range_raises():
    with pytest.raises(ValueError):
        ORATSDimensionScore(ORATSCertificationDimension.VOLUME, 6, "x")


def test_missing_dimension_raises():
    incomplete = tuple(s for s in _all_dims_scored({}) if s.dimension != ORATSCertificationDimension.VOLUME)
    with pytest.raises(ValueError):
        ORATSCertificationResult(scores=incomplete)


def test_critical_blockers_include_coverage():
    assert ORATSCertificationDimension.COVERAGE in CRITICAL_BLOCKER_DIMENSIONS
    assert ORATSCertificationDimension.CONTRACT_IDENTITY in CRITICAL_BLOCKER_DIMENSIONS
    assert ORATSCertificationDimension.HISTORICAL_CHAIN in CRITICAL_BLOCKER_DIMENSIONS
    assert ORATSCertificationDimension.PIT in CRITICAL_BLOCKER_DIMENSIONS


def test_synthetic_full_score_is_not_disqualified():
    result = ORATSCertificationResult(scores=_all_dims_scored({}))
    assert result.disqualified() is False


def test_synthetic_zero_coverage_disqualifies_regardless_of_other_scores():
    scores = tuple(ORATSDimensionScore(d, 0 if d == ORATSCertificationDimension.COVERAGE else 5, "r") for d in ORATSCertificationDimension)
    result = ORATSCertificationResult(scores=scores)
    assert result.total_score() == 5 * 14
    assert result.disqualified() is True
    assert evaluate_orats_gate(result) == ResearchReadinessGate.HISTORICAL_OPTIONS_DATA_INSUFFICIENT


def test_gate_thresholds_reachable():
    # 15 dims x 5 = 75 max. BACKTEST_READY needs 0.6*75=45 <= total < 0.8*75=60.
    # 10 dims at 4 + 5 dims at 3 = 40 + 15 = 55 -- squarely inside that bracket.
    fours = list(ORATSCertificationDimension)[:10]
    backtest_ready_scores = _all_dims_scored({d: 4 for d in fours})
    backtest_ready = ORATSCertificationResult(scores=backtest_ready_scores)
    assert 45 <= backtest_ready.total_score() < 60
    assert evaluate_orats_gate(backtest_ready) == ResearchReadinessGate.HISTORICAL_OPTIONS_BACKTEST_READY

    max_ = ORATSCertificationResult(scores=_all_dims_scored({d: 5 for d in ORATSCertificationDimension}))
    assert evaluate_orats_gate(max_) == ResearchReadinessGate.HISTORICAL_OPTIONS_PRODUCTION_RESEARCH_READY


def test_real_orats_certification_is_disqualified_via_coverage():
    """The real, current, honest result: zero real ORATS data exists
    this phase."""
    assert ORATS_CERTIFICATION.disqualified() is True
    assert ORATSCertificationDimension.COVERAGE in ORATS_CERTIFICATION.triggered_critical_blockers()
    assert ORATS_GATE == ResearchReadinessGate.HISTORICAL_OPTIONS_DATA_INSUFFICIENT


def test_no_real_dimension_scores_a_perfect_five():
    """Nothing this phase found was ever verified by an actual API
    call -- no dimension should claim full confidence."""
    for s in ORATS_CERTIFICATION.scores:
        assert s.score < 5, s.dimension


def test_every_real_score_cites_a_rationale():
    for s in ORATS_CERTIFICATION.scores:
        assert len(s.rationale) > 15, s.dimension
