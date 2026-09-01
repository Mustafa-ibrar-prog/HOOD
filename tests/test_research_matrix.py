"""Tests for the research matrix (Phase 5, section 17) — evidence, never
a ranking."""

from __future__ import annotations

from src.research.classification import ClassificationResult, StrategyClassification
from src.research.research_matrix import ResearchMatrix, ResearchMatrixRow


def _row(hypothesis_id: str, classification: StrategyClassification) -> ResearchMatrixRow:
    return ResearchMatrixRow(
        hypothesis_id=hypothesis_id, strategy_name=f"{hypothesis_id} strategy",
        is_evidence="positive", validation_evidence="mixed", oos_evidence="negative",
        parameter_stability="unstable", time_stability="n/a", universe_stability="n/a",
        regime_stability="n/a", cost_sensitivity="fails at 2x", execution_sensitivity="fails with delay",
        placebo_bootstrap_evidence="CI includes zero", sample_size=30,
        known_biases=("survivorship",), limitations=("thin universe",),
        classification=ClassificationResult(classification, ("test reason",)),
    )


def test_matrix_preserves_input_order_never_sorts_by_performance():
    rows = [_row("REJ-001", StrategyClassification.REJECTED), _row("PROM-001", StrategyClassification.PROMISING)]
    matrix = ResearchMatrix(rows=tuple(rows))
    # REJ-001 was passed first and must stay first, even though PROM-001
    # "looks better" — this module must never reorder by outcome.
    assert matrix.rows[0].hypothesis_id == "REJ-001"
    assert matrix.rows[1].hypothesis_id == "PROM-001"


def test_matrix_render_includes_every_row_and_field():
    rows = [_row("MOM-001", StrategyClassification.REJECTED)]
    matrix = ResearchMatrix(rows=tuple(rows))
    text = matrix.render()
    assert "MOM-001" in text
    assert "REJECTED" in text
    assert "survivorship" in text
    assert "thin universe" in text
    assert "NOT a ranking" in text
