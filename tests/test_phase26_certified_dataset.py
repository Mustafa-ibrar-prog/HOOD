"""Phase 26, Part 10/11/16 — sanity checks on the ACTUAL certification
result this phase produced for the real QuantConnect/Lean sample."""

from __future__ import annotations

from src.options.phase26_certification_score import CertificationDimension
from src.options.phase26_certified_dataset import FINAL_GATE, QUANTCONNECT_LEAN_SAMPLE_CERTIFICATION
from src.options.phase26_final_gate import ResearchReadinessGate


def test_certification_covers_all_fifteen_dimensions():
    dims = {s.dimension for s in QUANTCONNECT_LEAN_SAMPLE_CERTIFICATION.scores}
    assert dims == set(CertificationDimension)


def test_certification_is_not_disqualified():
    """None of the real evidence gathered this phase hit a 0/5 on any
    critical-blocker dimension."""
    assert QUANTCONNECT_LEAN_SAMPLE_CERTIFICATION.disqualified() is False


def test_every_real_score_cites_real_evidence():
    for s in QUANTCONNECT_LEAN_SAMPLE_CERTIFICATION.scores:
        assert len(s.evidence) > 15, s.dimension
        assert len(s.rationale) > 15, s.dimension


def test_no_dimension_claims_a_perfect_score():
    """Nothing this phase found was fully, unconditionally verified --
    a 5/5 anywhere would overclaim."""
    for s in QUANTCONNECT_LEAN_SAMPLE_CERTIFICATION.scores:
        assert s.score < 5, s.dimension


def test_iv_and_greeks_score_low_reflecting_no_native_vendor_field():
    assert QUANTCONNECT_LEAN_SAMPLE_CERTIFICATION.score_for(CertificationDimension.IMPLIED_VOLATILITY) <= 2
    assert QUANTCONNECT_LEAN_SAMPLE_CERTIFICATION.score_for(CertificationDimension.GREEKS) <= 2


def test_final_gate_is_partial_reflecting_narrow_coverage():
    """This phase's own honest coverage_is_general_purpose=False finding
    (no NVDA/TSLA, narrow date range) must be reflected in the final
    gate, not overridden by strong per-field scores."""
    assert FINAL_GATE == ResearchReadinessGate.HISTORICAL_OPTIONS_DATA_PARTIAL


def test_final_gate_is_one_of_the_five_required_values():
    assert FINAL_GATE in set(ResearchReadinessGate)
