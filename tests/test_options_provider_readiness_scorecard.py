"""Phase 25, Part 20 — the quantitative readiness scorecard: every
dimension present, scores in range, the critical-blocker override rule
correctly implemented and correctly NOT triggered by ORATS's actual
evidence."""

from __future__ import annotations

import pytest

from src.options.provider_readiness_scorecard import (
    CRITICAL_BLOCKER_DIMENSIONS,
    ORATS_READINESS_SCORECARD,
    DimensionScore,
    ProviderReadinessScorecard,
    ScorecardDimension,
)


def test_scorecard_covers_all_fifteen_dimensions():
    assert len(ScorecardDimension) == 15
    assert len(ORATS_READINESS_SCORECARD.scores) == 15


def test_every_score_is_in_range():
    for s in ORATS_READINESS_SCORECARD.scores:
        assert 0 <= s.score <= 5


def test_dimension_score_rejects_out_of_range_values():
    with pytest.raises(ValueError):
        DimensionScore(ScorecardDimension.VOLUME, 6, "bad")
    with pytest.raises(ValueError):
        DimensionScore(ScorecardDimension.VOLUME, -1, "bad")


def test_scorecard_rejects_missing_dimensions():
    incomplete = tuple(s for s in ORATS_READINESS_SCORECARD.scores if s.dimension != ScorecardDimension.VOLUME)
    with pytest.raises(ValueError):
        ProviderReadinessScorecard(provider="X", scores=incomplete)


def test_four_critical_blocker_dimensions_match_the_prompts_literal_list():
    assert CRITICAL_BLOCKER_DIMENSIONS == frozenset({
        ScorecardDimension.EXPIRED_CONTRACTS,
        ScorecardDimension.BID_ASK_HISTORICAL,
        ScorecardDimension.HISTORICAL_CHAIN,
        ScorecardDimension.CONTRACT_IDENTITY,
    })


def test_orats_scorecard_is_not_disqualified():
    """None of ORATS's 4 critical-blocker dimensions scored 0 -- every
    one has at least weak, real schema-grounded evidence."""
    assert ORATS_READINESS_SCORECARD.disqualified() is False
    assert ORATS_READINESS_SCORECARD.triggered_critical_blockers() == ()


def test_a_synthetic_zero_critical_score_does_disqualify():
    """Prove the override rule actually fires, not just that it happens
    to be inactive for ORATS's real numbers."""
    scores = tuple(
        DimensionScore(s.dimension, 0, "synthetic") if s.dimension == ScorecardDimension.HISTORICAL_CHAIN else s
        for s in ORATS_READINESS_SCORECARD.scores
    )
    synthetic = ProviderReadinessScorecard(provider="SYNTHETIC_DISQUALIFIED", scores=scores)
    assert synthetic.disqualified() is True
    assert ScorecardDimension.HISTORICAL_CHAIN in synthetic.triggered_critical_blockers()


def test_a_high_total_score_with_a_triggered_blocker_still_disqualifies():
    """The override must win regardless of total score (Part 20's exact
    wording)."""
    scores = tuple(
        DimensionScore(s.dimension, 0, "synthetic") if s.dimension == ScorecardDimension.EXPIRED_CONTRACTS
        else DimensionScore(s.dimension, 5, "synthetic max")
        for s in ORATS_READINESS_SCORECARD.scores
    )
    synthetic = ProviderReadinessScorecard(provider="SYNTHETIC_HIGH_SCORE_BUT_BLOCKED", scores=scores)
    assert synthetic.total_score() == 5 * 14  # every other dimension maxed
    assert synthetic.disqualified() is True


def test_total_and_max_possible_score_are_consistent():
    sc = ORATS_READINESS_SCORECARD
    assert sc.max_possible_score() == 75
    assert 0 <= sc.total_score() <= sc.max_possible_score()


def test_no_dimension_score_claims_a_5_without_real_schema_evidence_language():
    """A 5/5 would mean fully verified -- nothing in this phase reached
    that bar (Part 3/19's evidence discipline)."""
    for s in ORATS_READINESS_SCORECARD.scores:
        assert s.score < 5, f"{s.dimension} scored a perfect 5 -- no dimension was independently verified this phase"
