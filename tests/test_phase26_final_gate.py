"""Phase 26, Part 11/15 — the minimum research-ready standard gates:
each of the 5 exact classifications is reachable, disqualification
always yields INSUFFICIENT, and per-field quality never silently
substitutes for genuine coverage breadth."""

from __future__ import annotations

from src.options.phase26_certification_score import CertificationDimension, DatasetCertificationScore, DimensionScore
from src.options.phase26_final_gate import ResearchReadinessGate, evaluate_gate


def _score(overrides: dict) -> DatasetCertificationScore:
    scores = tuple(DimensionScore(d, overrides.get(d, 3), "r", "e") for d in CertificationDimension)
    return DatasetCertificationScore(dataset_label="X", scores=scores)


def test_disqualified_score_yields_insufficient_regardless_of_coverage_flag():
    sc = _score({CertificationDimension.CONTRACT_IDENTITY: 0})
    assert evaluate_gate(sc, coverage_is_general_purpose=True) == ResearchReadinessGate.HISTORICAL_OPTIONS_DATA_INSUFFICIENT
    assert evaluate_gate(sc, coverage_is_general_purpose=False) == ResearchReadinessGate.HISTORICAL_OPTIONS_DATA_INSUFFICIENT


def test_weak_core_dimensions_yield_partial():
    sc = _score({CertificationDimension.CONTRACT_IDENTITY: 1})
    assert evaluate_gate(sc, coverage_is_general_purpose=True) == ResearchReadinessGate.HISTORICAL_OPTIONS_DATA_PARTIAL


def test_narrow_coverage_caps_at_partial_even_with_strong_scores():
    """Part 11's explicit instruction: do not call something
    backtest-ready merely because the fields score well -- coverage
    breadth is a separate gate."""
    sc = _score({d: 5 for d in CertificationDimension})
    assert evaluate_gate(sc, coverage_is_general_purpose=False) == ResearchReadinessGate.HISTORICAL_OPTIONS_DATA_PARTIAL


def test_research_ready_when_core_dims_adequate_but_bid_ask_weak():
    sc = _score({CertificationDimension.HISTORICAL_BID_ASK: 1})
    assert evaluate_gate(sc, coverage_is_general_purpose=True) == ResearchReadinessGate.HISTORICAL_OPTIONS_RESEARCH_READY


def test_backtest_ready_when_bid_ask_and_execution_realism_adequate_but_licensing_weak():
    sc = _score({CertificationDimension.LICENSING_ACCESS_CLARITY: 1})
    assert evaluate_gate(sc, coverage_is_general_purpose=True) == ResearchReadinessGate.HISTORICAL_OPTIONS_BACKTEST_READY


def test_production_ready_when_everything_adequate_and_coverage_is_general():
    sc = _score({})
    assert evaluate_gate(sc, coverage_is_general_purpose=True) == ResearchReadinessGate.HISTORICAL_OPTIONS_PRODUCTION_RESEARCH_READY


def test_all_five_gate_values_are_exactly_part_11s_vocabulary():
    assert {g.value for g in ResearchReadinessGate} == {
        "historical_options_data_insufficient", "historical_options_data_partial",
        "historical_options_research_ready", "historical_options_backtest_ready",
        "historical_options_production_research_ready",
    }
