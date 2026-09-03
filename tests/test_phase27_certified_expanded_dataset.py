"""Phase 27, Part 6/10/14/16 — sanity checks on the ACTUAL expanded
certification result this phase produced."""

from __future__ import annotations

from src.options.phase26_certification_score import CertificationDimension
from src.options.phase26_final_gate import ResearchReadinessGate
from src.options.phase27_certified_expanded_dataset import EXPANDED_DATASET_CERTIFICATION, EXPANDED_FINAL_GATE


def test_certification_covers_all_fifteen_dimensions():
    dims = {s.dimension for s in EXPANDED_DATASET_CERTIFICATION.scores}
    assert dims == set(CertificationDimension)


def test_certification_is_not_disqualified():
    assert EXPANDED_DATASET_CERTIFICATION.disqualified() is False


def test_every_real_score_cites_real_evidence():
    for s in EXPANDED_DATASET_CERTIFICATION.scores:
        assert len(s.evidence) > 15, s.dimension
        assert len(s.rationale) > 15, s.dimension


def test_no_dimension_claims_a_perfect_score():
    for s in EXPANDED_DATASET_CERTIFICATION.scores:
        assert s.score < 5, s.dimension


def test_total_score_improved_over_phase26_without_any_dimension_regressing():
    """Part 6: 'must not weaken the certification standard.' Every
    dimension score here must be >= Phase 26's corresponding score."""
    from src.options.phase26_certified_dataset import QUANTCONNECT_LEAN_SAMPLE_CERTIFICATION as PHASE26_CERT
    for dim in CertificationDimension:
        phase26_score = PHASE26_CERT.score_for(dim)
        phase27_score = EXPANDED_DATASET_CERTIFICATION.score_for(dim)
        assert phase27_score >= phase26_score, f"{dim} regressed: {phase26_score} -> {phase27_score}"
    assert EXPANDED_DATASET_CERTIFICATION.total_score() >= PHASE26_CERT.total_score()


def test_corporate_actions_score_improved_reflecting_the_real_investigation():
    from src.options.phase26_certified_dataset import QUANTCONNECT_LEAN_SAMPLE_CERTIFICATION as PHASE26_CERT
    assert EXPANDED_DATASET_CERTIFICATION.score_for(CertificationDimension.CORPORATE_ACTIONS) > \
        PHASE26_CERT.score_for(CertificationDimension.CORPORATE_ACTIONS)


def test_final_gate_stays_partial_despite_the_higher_score():
    """Part 14's explicit instruction: do not upgrade merely because the
    aggregate score is high -- coverage breadth against the project's
    real target underlyings is still the binding constraint."""
    assert EXPANDED_FINAL_GATE == ResearchReadinessGate.HISTORICAL_OPTIONS_DATA_PARTIAL


def test_final_gate_is_one_of_the_five_required_values():
    assert EXPANDED_FINAL_GATE in set(ResearchReadinessGate)
