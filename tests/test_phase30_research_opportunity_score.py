"""Phase 30, Part 4/17 — the research OpportunityScore architecture."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.options.contract_selection import evaluate_contracts
from src.options.research_dataset import build_research_observations
from src.options.research_features import compute_features
from src.options.research_opportunity_score import (
    NOT_COMPUTED_THIS_PHASE,
    NullScoringMethod,
    ResearchOpportunityScore,
    score_rows,
)
from tests.phase30_fixtures import synthetic_multi_bar_store


def test_score_without_method_but_with_a_value_raises():
    with pytest.raises(ValueError):
        ResearchOpportunityScore(
            option_id="X", observation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            opportunity_score=0.9,
        )


def test_score_with_placeholder_method_and_no_values_is_fine():
    s = ResearchOpportunityScore(option_id="X", observation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert s.scoring_method == NOT_COMPUTED_THIS_PHASE
    assert s.opportunity_score is None


def test_null_scoring_method_never_computes_a_real_score():
    store = synthetic_multi_bar_store(n_bars=5)
    rows = build_research_observations(store)
    features = compute_features(rows)
    selections = evaluate_contracts(rows)
    scores = score_rows(rows, features, selections, method=NullScoringMethod())
    assert len(scores) == len(rows)
    for s in scores:
        assert s.scoring_method == NOT_COMPUTED_THIS_PHASE
        assert s.opportunity_score is None
        assert s.confidence is None
        assert s.expected_return is None
        assert s.expected_risk is None
        assert s.liquidity_score is None
        assert s.execution_score is None
        assert s.data_quality_score is None
        assert "NO_SCORING_METHOD_IMPLEMENTED_THIS_PHASE" in s.reason_codes


def test_reason_codes_reflect_rejected_selection():
    store = synthetic_multi_bar_store(n_bars=1)
    rows = build_research_observations(store)
    features = compute_features(rows)
    from src.options.contract_selection import SelectionCriteria
    strict = SelectionCriteria(min_volume=99999.0)
    selections = evaluate_contracts(rows, strict)
    scores = score_rows(rows, features, selections, method=NullScoringMethod())
    assert "REJECTED_BY_SELECTION" in scores[0].reason_codes


def test_misaligned_rows_are_skipped_not_fabricated():
    store = synthetic_multi_bar_store(n_bars=3)
    rows = build_research_observations(store)
    features = compute_features(rows)
    selections = evaluate_contracts(rows)
    # Drop one selection -- its corresponding observation must be skipped, not scored with a fabricated selection.
    scores = score_rows(rows, features, selections[:-1], method=NullScoringMethod())
    assert len(scores) == len(rows) - 1


def test_no_new_scoring_method_registers_a_real_alpha_hypothesis():
    """Structural safety check for Part 10 -- the only ScoringMethod
    subclass this module defines is the null one."""
    import src.options.research_opportunity_score as mod
    from src.options.research_opportunity_score import ScoringMethod
    subclasses = [
        v for v in vars(mod).values()
        if isinstance(v, type) and issubclass(v, ScoringMethod) and v is not ScoringMethod
    ]
    assert subclasses == [NullScoringMethod]
