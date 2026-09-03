"""Phase 28, Part 8/17 — provider scorecard: structural correctness,
the critical-blocker override (exercised via a synthetic disqualifying
case, not just the real finalists' own non-disqualifying numbers), and
the real elimination/ranking logic."""

from __future__ import annotations

import pytest

from src.options.phase28_provider_scorecard import (
    ALL_SCORECARDS,
    CRITICAL_BLOCKER_DIMENSIONS,
    DATABENTO_SCORECARD,
    ORATS_SCORECARD,
    POLYGON_MASSIVE_SCORECARD,
    THETADATA_SCORECARD,
    ProviderDimensionScore,
    ProviderScorecard,
    ProviderScorecardDimension,
    non_eliminated_scorecards,
    ranked_by_total_score,
)


def test_exactly_twenty_dimensions():
    assert len(ProviderScorecardDimension) == 20


def test_ten_total_providers_evaluated():
    assert len(ALL_SCORECARDS) == 10


def test_four_finalists_are_not_eliminated():
    non_elim = {sc.provider for sc in non_eliminated_scorecards()}
    assert non_elim == {"ORATS", "ThetaData", "Databento", "Polygon.io / Massive"}


def test_six_providers_eliminated_with_a_real_reason():
    eliminated = [sc for sc in ALL_SCORECARDS if sc.eliminated]
    assert len(eliminated) == 6
    for sc in eliminated:
        assert len(sc.elimination_reason) > 20
        assert sc.disqualified() is True


def test_every_finalist_covers_all_twenty_dimensions():
    for sc in non_eliminated_scorecards():
        dims = {s.dimension for s in sc.scores}
        assert dims == set(ProviderScorecardDimension)


def test_score_out_of_range_raises():
    with pytest.raises(ValueError):
        ProviderDimensionScore(ProviderScorecardDimension.VOLUME, 6, "x")


def test_no_finalist_is_disqualified():
    for sc in non_eliminated_scorecards():
        assert sc.disqualified() is False, sc.provider


def test_synthetic_zero_critical_score_does_disqualify():
    scores = tuple(
        ProviderDimensionScore(s.dimension, 0, "synthetic") if s.dimension == ProviderScorecardDimension.CONTRACT_IDENTITY else s
        for s in ORATS_SCORECARD.scores
    )
    synthetic = ProviderScorecard(provider="SYNTHETIC_TEST_PROVIDER", scores=scores)
    assert synthetic.disqualified() is True
    assert ProviderScorecardDimension.CONTRACT_IDENTITY in synthetic.triggered_critical_blockers()


def test_licensing_clarity_is_not_a_critical_blocker_dimension():
    """Every real finalist scores 0 on LICENSING_CLARITY -- if it were a
    blocker, ALL 4 finalists would be disqualified, contradicting the
    module's own real, non-eliminated ranking."""
    assert ProviderScorecardDimension.LICENSING_CLARITY not in CRITICAL_BLOCKER_DIMENSIONS
    for sc in non_eliminated_scorecards():
        assert sc.score_for(ProviderScorecardDimension.LICENSING_CLARITY) == 0


def test_ranked_by_total_score_orders_correctly():
    ranking = ranked_by_total_score()
    assert ranking[0].provider == "ORATS"
    scores = [sc.total_score() for sc in ranking]
    assert scores == sorted(scores, reverse=True)


def test_orats_scores_highest_total():
    assert ORATS_SCORECARD.total_score() == max(sc.total_score() for sc in non_eliminated_scorecards())


def test_no_finalist_scores_a_perfect_dimension_without_real_justification():
    """No candidate ever reached OWN_LIVE_API_PROBE-tier evidence any
    phase -- nothing should be able to score a bare, unjustified 5 with
    an empty rationale."""
    for sc in non_eliminated_scorecards():
        for s in sc.scores:
            assert len(s.rationale) > 10, (sc.provider, s.dimension)
