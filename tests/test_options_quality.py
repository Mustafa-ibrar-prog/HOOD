"""Phase 18, Part 22/17 — option-specific data quality checks."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.options.chain import OptionChainObservation
from src.options.greeks import Greeks
from src.options.implied_volatility import IVObservation
from src.options.instrument import OptionContract
from src.options.quality import (
    find_duplicate_contract_timestamp,
    find_inconsistent_contract_metadata,
    find_timestamp_ordering_issues,
    validate_greeks,
    validate_iv,
    validate_observation,
)

CONTRACT = OptionContract(underlying_symbol="AAPL", option_id="c55a630e-a0b9-45ab-b889-47bee291fee7", call_put="call", strike=175.0, expiration=date(2022, 1, 21))


def test_valid_observation_has_no_issues():
    obs = OptionChainObservation.from_live_quote(CONTRACT, observation_timestamp=datetime(2021, 12, 1, tzinfo=timezone.utc), bid=1.0, ask=1.5, last=1.2, volume=10, open_interest=100)
    assert validate_observation(obs) == []


def test_negative_bid_flagged():
    obs = OptionChainObservation.from_live_quote(CONTRACT, observation_timestamp=datetime(2021, 12, 1, tzinfo=timezone.utc), bid=-1.0, ask=1.5, last=1.2, volume=10, open_interest=100)
    issues = validate_observation(obs)
    assert any(i.code == "NEGATIVE_BID" for i in issues)


def test_negative_ask_flagged():
    obs = OptionChainObservation.from_live_quote(CONTRACT, observation_timestamp=datetime(2021, 12, 1, tzinfo=timezone.utc), bid=1.0, ask=-1.5, last=1.2, volume=10, open_interest=100)
    issues = validate_observation(obs)
    assert any(i.code == "NEGATIVE_ASK" for i in issues)


def test_bid_exceeds_ask_flagged():
    obs = OptionChainObservation.from_live_quote(CONTRACT, observation_timestamp=datetime(2021, 12, 1, tzinfo=timezone.utc), bid=5.0, ask=1.0, last=2.0, volume=10, open_interest=100)
    issues = validate_observation(obs)
    assert any(i.code == "BID_EXCEEDS_ASK" for i in issues)


def test_expired_contract_observed_after_expiration_flagged():
    obs = OptionChainObservation.from_historical_bar(CONTRACT, observation_timestamp=datetime(2022, 2, 1, tzinfo=timezone.utc), close_price=0.0)
    issues = validate_observation(obs)
    assert any(i.code == "EXPIRED_CONTRACT_OBSERVED_AFTER_EXPIRATION" for i in issues)


def test_observation_before_expiration_not_flagged():
    obs = OptionChainObservation.from_historical_bar(CONTRACT, observation_timestamp=datetime(2021, 12, 1, tzinfo=timezone.utc), close_price=3.53)
    issues = validate_observation(obs)
    assert not any(i.code == "EXPIRED_CONTRACT_OBSERVED_AFTER_EXPIRATION" for i in issues)


def test_inconsistent_multiplier_flagged():
    bad = OptionContract(underlying_symbol="AAPL", option_id="x", call_put="call", strike=175.0, expiration=date(2022, 1, 21), contract_multiplier=200, is_standard_deliverable=True)
    obs = OptionChainObservation.from_historical_bar(bad, observation_timestamp=datetime(2021, 12, 1, tzinfo=timezone.utc), close_price=1.0)
    issues = validate_observation(obs)
    assert any(i.code == "INCONSISTENT_MULTIPLIER" for i in issues)


def test_non_standard_deliverable_with_note_not_flagged():
    adjusted = OptionContract(underlying_symbol="AAPL", option_id="x", call_put="call", strike=175.0, expiration=date(2022, 1, 21), contract_multiplier=300, is_standard_deliverable=False, deliverable_note="split-adjusted")
    obs = OptionChainObservation.from_historical_bar(adjusted, observation_timestamp=datetime(2021, 12, 1, tzinfo=timezone.utc), close_price=1.0)
    issues = validate_observation(obs)
    assert not any(i.code == "INCONSISTENT_MULTIPLIER" for i in issues)


def test_valid_delta_range_not_flagged():
    g = Greeks.observed(delta=0.98, gamma=0.001, theta=-0.1, vega=0.03, rho=0.1)
    assert validate_greeks(g) == []


def test_invalid_delta_flagged():
    g = Greeks.observed(delta=1.5, gamma=0.001, theta=-0.1, vega=0.03, rho=0.1)
    issues = validate_greeks(g)
    assert any(i.code == "INVALID_DELTA" for i in issues)


def test_negative_gamma_flagged():
    g = Greeks.observed(delta=0.5, gamma=-0.001, theta=-0.1, vega=0.03, rho=0.1)
    issues = validate_greeks(g)
    assert any(i.code == "INVALID_GAMMA" for i in issues)


def test_negative_vega_flagged():
    g = Greeks.observed(delta=0.5, gamma=0.001, theta=-0.1, vega=-0.03, rho=0.1)
    issues = validate_greeks(g)
    assert any(i.code == "INVALID_VEGA" for i in issues)


def test_reasonable_iv_not_flagged():
    assert validate_iv(IVObservation.observed(0.82)) == []


def test_extreme_iv_flagged_as_warning_not_rejected():
    issues = validate_iv(IVObservation.observed(12.0))
    assert len(issues) == 1
    assert issues[0].code == "EXTREME_IV"
    assert issues[0].severity == "WARNING"


def test_find_duplicate_contract_timestamp():
    ts = datetime(2021, 12, 1, tzinfo=timezone.utc)
    a = OptionChainObservation.from_historical_bar(CONTRACT, observation_timestamp=ts, close_price=1.0)
    b = OptionChainObservation.from_historical_bar(CONTRACT, observation_timestamp=ts, close_price=1.0)
    dupes = find_duplicate_contract_timestamp([a, b])
    assert len(dupes) == 1


def test_find_timestamp_ordering_issues():
    early = OptionChainObservation.from_historical_bar(CONTRACT, observation_timestamp=datetime(2021, 12, 1, tzinfo=timezone.utc), close_price=1.0)
    late = OptionChainObservation.from_historical_bar(CONTRACT, observation_timestamp=datetime(2021, 12, 5, tzinfo=timezone.utc), close_price=1.0)
    assert find_timestamp_ordering_issues([late, early]) == [1]
    assert find_timestamp_ordering_issues([early, late]) == []


def test_find_inconsistent_contract_metadata():
    a = CONTRACT
    b = OptionContract(underlying_symbol="AAPL", option_id=CONTRACT.option_id, call_put="put", strike=175.0, expiration=date(2022, 1, 21))  # same id, different call_put -- a real identity violation
    issues = find_inconsistent_contract_metadata([a, b])
    assert any(i.code == "INCONSISTENT_CALL_PUT" for i in issues)


def test_consistent_contract_metadata_no_issues():
    issues = find_inconsistent_contract_metadata([CONTRACT, CONTRACT])
    assert issues == []
