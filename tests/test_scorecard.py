"""Phase 7, Part 16 & 19: research scorecard tests."""

from __future__ import annotations

import pytest

from src.research.scorecard import DimensionVerdict, ScorecardDimension, build_scorecard, classify_with_scorecard


def _dim(name, verdict):
    return ScorecardDimension(name=name, verdict=verdict, detail="test")


def test_unknown_dimension_name_rejected():
    with pytest.raises(ValueError):
        ScorecardDimension(name="not_a_real_dimension", verdict=DimensionVerdict.SUPPORTS, detail="x")


def test_mostly_not_applicable_classifies_not_ready():
    dims = [_dim("statistical_evidence", DimensionVerdict.SUPPORTS)]  # only 1 of 12 evaluated
    scorecard = build_scorecard("H1", dims)
    assert scorecard.classification == "NOT_READY"
    assert sum(1 for d in scorecard.dimensions if d.verdict == DimensionVerdict.NOT_APPLICABLE) == 11


def test_statistical_evidence_against_forces_rejected():
    dims = [
        _dim("statistical_evidence", DimensionVerdict.AGAINST),
        _dim("economic_significance", DimensionVerdict.SUPPORTS),
        _dim("data_quality", DimensionVerdict.SUPPORTS),
        _dim("economic_rationale", DimensionVerdict.SUPPORTS),
        _dim("research_contamination_risk", DimensionVerdict.SUPPORTS),
    ]
    scorecard = build_scorecard("H1", dims)
    assert scorecard.classification == "REJECTED"


def test_economic_significance_against_also_forces_rejected():
    dims = [
        _dim("statistical_evidence", DimensionVerdict.SUPPORTS),
        _dim("economic_significance", DimensionVerdict.AGAINST),
        _dim("data_quality", DimensionVerdict.SUPPORTS),
        _dim("economic_rationale", DimensionVerdict.SUPPORTS),
        _dim("research_contamination_risk", DimensionVerdict.SUPPORTS),
    ]
    scorecard = build_scorecard("H1", dims)
    assert scorecard.classification == "REJECTED"


def test_mostly_supports_classifies_promising():
    names = ["statistical_evidence", "economic_significance", "out_of_sample_stability", "parameter_stability", "cost_robustness"]
    dims = [_dim(n, DimensionVerdict.SUPPORTS) for n in names]
    scorecard = build_scorecard("H1", dims)
    assert scorecard.classification == "PROMISING"


def test_mixed_evidence_classifies_inconclusive():
    names = ["statistical_evidence", "economic_significance", "out_of_sample_stability", "parameter_stability", "cost_robustness"]
    verdicts = [DimensionVerdict.SUPPORTS, DimensionVerdict.NEUTRAL, DimensionVerdict.SUPPORTS, DimensionVerdict.NEUTRAL, DimensionVerdict.NEUTRAL]
    dims = [_dim(n, v) for n, v in zip(names, verdicts)]
    scorecard = build_scorecard("H1", dims)
    assert scorecard.classification == "INCONCLUSIVE"


def test_mostly_neutral_or_against_classifies_fragile():
    names = ["statistical_evidence", "economic_significance", "out_of_sample_stability", "parameter_stability", "cost_robustness"]
    verdicts = [DimensionVerdict.SUPPORTS, DimensionVerdict.SUPPORTS, DimensionVerdict.NEUTRAL, DimensionVerdict.NEUTRAL, DimensionVerdict.NEUTRAL]
    dims = [_dim(n, v) for n, v in zip(names, verdicts)]
    scorecard = build_scorecard("H1", dims)
    # supports_fraction = 2/5 = 0.4 -> INCONCLUSIVE boundary; drop one more support to force FRAGILE
    dims2 = [_dim(n, DimensionVerdict.NEUTRAL) for n in names[:-1]] + [_dim(names[-1], DimensionVerdict.SUPPORTS)]
    scorecard2 = build_scorecard("H1", dims2)
    assert scorecard2.classification == "FRAGILE"


def test_never_collapses_to_a_single_score_all_12_dimensions_always_present():
    from src.research.scorecard import SCORECARD_DIMENSIONS

    dims = [_dim("statistical_evidence", DimensionVerdict.SUPPORTS)]
    scorecard = build_scorecard("H1", dims)
    assert len(scorecard.dimensions) == 12
    assert {d.name for d in scorecard.dimensions} == set(SCORECARD_DIMENSIONS)


def test_classify_with_scorecard_is_a_pure_function_of_its_input():
    dims = [_dim("statistical_evidence", DimensionVerdict.SUPPORTS)] * 1 + [
        _dim(n, DimensionVerdict.NOT_APPLICABLE) for n in ["economic_significance", "out_of_sample_stability", "parameter_stability", "regime_stability", "universe_stability", "cost_robustness", "execution_robustness", "data_quality", "multiple_testing_penalty", "research_contamination_risk", "economic_rationale"]
    ]
    c1, r1 = classify_with_scorecard(dims)
    c2, r2 = classify_with_scorecard(dims)
    assert c1 == c2 and r1 == r2
