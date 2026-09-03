"""Phase 26, Part 10/15 — the dataset certification score's structural
correctness, including the critical-blocker override rule exercised via
a synthetic case, not just the real instance's own numbers."""

from __future__ import annotations

import pytest

from src.options.phase26_certification_score import (
    CRITICAL_BLOCKER_DIMENSIONS,
    CertificationDimension,
    DatasetCertificationScore,
    DimensionScore,
)


def _all_dims_scored(score_map: dict) -> tuple:
    return tuple(DimensionScore(d, score_map.get(d, 3), "r", "e") for d in CertificationDimension)


def test_all_fifteen_dimensions_required():
    assert len(CertificationDimension) == 15


def test_score_out_of_range_raises():
    with pytest.raises(ValueError):
        DimensionScore(CertificationDimension.VOLUME, 6, "r", "e")
    with pytest.raises(ValueError):
        DimensionScore(CertificationDimension.VOLUME, -1, "r", "e")


def test_missing_dimension_raises():
    incomplete = tuple(s for s in _all_dims_scored({}) if s.dimension != CertificationDimension.VOLUME)
    with pytest.raises(ValueError):
        DatasetCertificationScore(dataset_label="X", scores=incomplete)


def test_critical_blocker_dimensions_match_part_10():
    assert CRITICAL_BLOCKER_DIMENSIONS == frozenset({
        CertificationDimension.CONTRACT_IDENTITY,
        CertificationDimension.POINT_IN_TIME_SAFETY,
        CertificationDimension.TIMESTAMP_QUALITY,
        CertificationDimension.LICENSING_ACCESS_CLARITY,
    })


def test_not_disqualified_when_no_blocker_scores_zero():
    sc = DatasetCertificationScore(dataset_label="X", scores=_all_dims_scored({}))
    assert sc.disqualified() is False
    assert sc.triggered_critical_blockers() == ()


def test_disqualified_when_a_blocker_dimension_scores_zero():
    sc = DatasetCertificationScore(dataset_label="X", scores=_all_dims_scored({CertificationDimension.CONTRACT_IDENTITY: 0}))
    assert sc.disqualified() is True
    assert CertificationDimension.CONTRACT_IDENTITY in sc.triggered_critical_blockers()


def test_high_total_score_does_not_override_a_triggered_blocker():
    """Part 10's explicit override rule."""
    scores = tuple(DimensionScore(d, 0 if d == CertificationDimension.TIMESTAMP_QUALITY else 5, "r", "e") for d in CertificationDimension)
    sc = DatasetCertificationScore(dataset_label="X", scores=scores)
    assert sc.total_score() == 5 * 14
    assert sc.disqualified() is True


def test_non_blocker_dimension_scoring_zero_does_not_disqualify():
    sc = DatasetCertificationScore(dataset_label="X", scores=_all_dims_scored({CertificationDimension.GREEKS: 0}))
    assert sc.disqualified() is False


def test_total_and_max_possible_score():
    sc = DatasetCertificationScore(dataset_label="X", scores=_all_dims_scored({}))
    assert sc.max_possible_score() == 75
    assert sc.total_score() == 3 * 15


def test_score_for_returns_the_right_dimension():
    sc = DatasetCertificationScore(dataset_label="X", scores=_all_dims_scored({CertificationDimension.GREEKS: 1}))
    assert sc.score_for(CertificationDimension.GREEKS) == 1
    assert sc.score_for(CertificationDimension.VOLUME) == 3
