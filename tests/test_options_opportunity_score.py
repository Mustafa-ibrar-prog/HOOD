"""Phase 19, Part 11/19 — the OpportunityScore pipeline schema, including
the required UNAVAILABLE_HISTORICALLY sentinel discipline."""

from __future__ import annotations

from datetime import date

import pytest

from src.options.chain import OptionsFieldStatus
from src.options.instrument import OptionContract
from src.options.opportunity_score import (
    UNAVAILABLE_HISTORICALLY,
    ChainCandidate,
    ContractCandidate,
    OpportunityScore,
    SignalEvaluation,
    UnderlyingCandidate,
)

CONTRACT = OptionContract(underlying_symbol="AAPL", option_id="c1", call_put="call", strike=150.0, expiration=date(2022, 1, 21))


def test_render_field_unavailable_by_default():
    cand = ContractCandidate(contract=CONTRACT, as_of=date(2022, 1, 3))
    assert cand.render_field("bid") == UNAVAILABLE_HISTORICALLY
    assert cand.render_field("implied_volatility") == UNAVAILABLE_HISTORICALLY


def test_render_field_returns_value_when_observed():
    cand = ContractCandidate(
        contract=CONTRACT, as_of=date(2022, 1, 3), close_price=5.0,
        field_status={"close_price": OptionsFieldStatus.OBSERVED},
    )
    assert cand.render_field("close_price") == "5.0"


def test_render_field_unavailable_when_status_is_unavailable_even_if_value_present():
    """A None-safety proof: if field_status doesn't mark it OBSERVED/DERIVED,
    the sentinel wins even though a stray numeric value exists on the field --
    never trust the raw attribute alone."""
    cand = ContractCandidate(contract=CONTRACT, as_of=date(2022, 1, 3), bid=3.5, field_status={"bid": OptionsFieldStatus.UNAVAILABLE})
    assert cand.render_field("bid") == UNAVAILABLE_HISTORICALLY


def test_render_field_derived_is_not_unavailable():
    cand = ContractCandidate(contract=CONTRACT, as_of=date(2022, 1, 3), delta=0.5, field_status={"delta": OptionsFieldStatus.DERIVED})
    assert cand.render_field("delta") == "0.5"


def test_chain_candidate_holds_contracts():
    cand = ContractCandidate(contract=CONTRACT, as_of=date(2022, 1, 3))
    chain = ChainCandidate(underlying_symbol="AAPL", expiration=date(2022, 1, 21), contracts=(cand,))
    assert len(chain.contracts) == 1


def test_underlying_candidate_holds_chains():
    cand = ContractCandidate(contract=CONTRACT, as_of=date(2022, 1, 3))
    chain = ChainCandidate(underlying_symbol="AAPL", expiration=date(2022, 1, 21), contracts=(cand,))
    underlying = UnderlyingCandidate(underlying_symbol="AAPL", chains=(chain,))
    assert underlying.chains[0].contracts[0].contract.option_id == "c1"


def test_opportunity_score_defaults_to_not_computed():
    score = OpportunityScore(contract_option_id="c1", signal_evaluations=())
    assert score.composite_score is None
    assert score.scoring_method == "NOT_COMPUTED_THIS_PHASE"


def test_opportunity_score_rejects_a_score_without_a_real_method():
    with pytest.raises(ValueError):
        OpportunityScore(contract_option_id="c1", signal_evaluations=(), composite_score=0.9)


def test_opportunity_score_accepts_a_score_with_a_real_method():
    score = OpportunityScore(contract_option_id="c1", signal_evaluations=(), composite_score=0.9, scoring_method="hypothetical_future_model_v1")
    assert score.composite_score == 0.9


def test_signal_evaluation_is_schema_only():
    sig = SignalEvaluation(signal_name="hypothetical_signal", contract_option_id="c1", raw_value=0.42, computed_at=date(2022, 1, 3))
    assert sig.raw_value == 0.42
