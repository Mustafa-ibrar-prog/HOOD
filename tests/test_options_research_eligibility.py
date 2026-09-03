"""Phase 20, Part 8/24 — the research-inclusion pipeline tests."""

from __future__ import annotations

from datetime import date

from src.options.contract_existence import ExistenceState
from src.options.instrument import OptionContract
from src.options.opportunity_score import UnderlyingCandidate
from src.options.research_eligibility import (
    ExclusionReason,
    InclusionReason,
    OptionChainCandidate,
    OptionContractCandidate,
    evaluate_underlying_inclusion,
    summarize_existence_impact,
)

CONTRACT = OptionContract(underlying_symbol="AAPL", option_id="c1", call_put="call", strike=150.0, expiration=date(2022, 6, 17))


def test_eligible_contract_with_full_history_and_unknown_existence():
    """The common real case: UNKNOWN_EXISTENCE alone does not exclude a
    contract (Part 4: excluding every UNKNOWN_EXISTENCE contract would
    empty the panel -- every real contract this codebase has ever seen
    carries this state)."""
    cand = OptionContractCandidate(contract=CONTRACT, bar_count=75, min_expected_bar_count=50, existence_state=ExistenceState.UNKNOWN_EXISTENCE)
    result = cand.evaluate()
    assert result.is_eligible is True
    assert InclusionReason.CONTRACT_INCLUDED_PRICE_HISTORY in result.inclusion_reasons
    assert result.has_unknown_existence is True


def test_contract_excluded_for_incomplete_history():
    cand = OptionContractCandidate(contract=CONTRACT, bar_count=10, min_expected_bar_count=50, existence_state=ExistenceState.UNKNOWN_EXISTENCE)
    result = cand.evaluate()
    assert result.is_eligible is False
    assert ExclusionReason.CONTRACT_EXCLUDED_INCOMPLETE_HISTORY in result.exclusion_reasons


def test_contract_excluded_for_known_expired():
    cand = OptionContractCandidate(contract=CONTRACT, bar_count=75, min_expected_bar_count=50, existence_state=ExistenceState.KNOWN_EXPIRED)
    result = cand.evaluate()
    assert result.is_eligible is False
    assert ExclusionReason.CONTRACT_EXCLUDED_INVALID_DATA in result.exclusion_reasons


def test_contract_excluded_for_insufficient_pit_evidence():
    cand = OptionContractCandidate(contract=CONTRACT, bar_count=75, min_expected_bar_count=50, existence_state=ExistenceState.INSUFFICIENT_PIT_EVIDENCE)
    result = cand.evaluate()
    assert result.is_eligible is False
    assert ExclusionReason.CONTRACT_EXCLUDED_INVALID_DATA in result.exclusion_reasons


def test_option_chain_candidate_is_included_requires_reasons_and_no_exclusions():
    chain = OptionChainCandidate(underlying_symbol="AAPL", expiration=date(2022, 6, 17), inclusion_reasons=(InclusionReason.UNDERLYING_INCLUDED_LIQUIDITY,))
    assert chain.is_included is True
    excluded_chain = OptionChainCandidate(underlying_symbol="AAPL", expiration=date(2022, 6, 17), inclusion_reasons=(InclusionReason.UNDERLYING_INCLUDED_LIQUIDITY,), exclusion_reasons=(ExclusionReason.CONTRACT_EXCLUDED_INVALID_DATA,))
    assert excluded_chain.is_included is False
    empty_chain = OptionChainCandidate(underlying_symbol="AAPL", expiration=date(2022, 6, 17), inclusion_reasons=())
    assert empty_chain.is_included is False


def test_evaluate_underlying_inclusion_verified():
    candidate = UnderlyingCandidate(underlying_symbol="AAPL", chains=())
    reasons = evaluate_underlying_inclusion(candidate, has_verified_historical_options=True)
    assert InclusionReason.UNDERLYING_INCLUDED_LIQUIDITY in reasons
    assert InclusionReason.UNDERLYING_INCLUDED_DATA_COVERAGE in reasons


def test_evaluate_underlying_inclusion_unverified():
    candidate = UnderlyingCandidate(underlying_symbol="XYZ", chains=())
    reasons = evaluate_underlying_inclusion(candidate, has_verified_historical_options=False)
    assert reasons == (ExclusionReason.UNDERLYING_EXCLUDED_NO_VERIFIED_HISTORICAL_OPTIONS,)


def test_summarize_existence_impact_all_unknown():
    summary = summarize_existence_impact([ExistenceState.UNKNOWN_EXISTENCE] * 10)
    assert summary.unknown_existence_fraction == 1.0
    assert summary.is_materially_affected is True


def test_summarize_existence_impact_none_unknown():
    summary = summarize_existence_impact([ExistenceState.KNOWN_EXISTENCE] * 10)
    assert summary.unknown_existence_fraction == 0.0
    assert summary.is_materially_affected is False


def test_summarize_existence_impact_empty():
    summary = summarize_existence_impact([])
    assert summary.unknown_existence_fraction == 0.0
