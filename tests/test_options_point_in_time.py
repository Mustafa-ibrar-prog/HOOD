"""Phase 18, Part 22 — PIT contract availability tests. No survivorship
bias: a contract's mere existence today (or in an "expired" listing)
must never be assumed to mean it existed at an arbitrary earlier
timestamp."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.options.instrument import OptionContract
from src.options.point_in_time import ContractExistenceEvidence, assert_no_survivorship_bias_in_contract_universe, contract_existed_at

CONTRACT = OptionContract(underlying_symbol="AAPL", option_id="c55a630e-a0b9-45ab-b889-47bee291fee7", call_put="call", strike=175.0, expiration=date(2022, 1, 21))


def test_existed_at_returns_false_after_expiration():
    ev = ContractExistenceEvidence(contract=CONTRACT, first_listed_date=None, expiration=date(2022, 1, 21), source="test")
    assert contract_existed_at(ev, as_of=datetime(2022, 6, 1, tzinfo=timezone.utc)) is False


def test_existed_at_returns_none_before_expiration_when_listing_unknown():
    """The honest answer given real data: this source never supplies a
    first-listed date, so 'did it exist on this date' before expiration
    is genuinely unknown -- must be None, not a guessed True."""
    ev = ContractExistenceEvidence(contract=CONTRACT, first_listed_date=None, expiration=date(2022, 1, 21), source="test")
    assert contract_existed_at(ev, as_of=datetime(2021, 6, 1, tzinfo=timezone.utc)) is None


def test_existed_at_returns_true_when_listing_date_known_and_as_of_within_window():
    ev = ContractExistenceEvidence(contract=CONTRACT, first_listed_date=date(2021, 11, 1), expiration=date(2022, 1, 21), source="test")
    assert contract_existed_at(ev, as_of=datetime(2021, 12, 1, tzinfo=timezone.utc)) is True


def test_existed_at_returns_false_before_known_listing_date():
    ev = ContractExistenceEvidence(contract=CONTRACT, first_listed_date=date(2021, 11, 1), expiration=date(2022, 1, 21), source="test")
    assert contract_existed_at(ev, as_of=datetime(2021, 10, 1, tzinfo=timezone.utc)) is False


def test_survivorship_bias_guard_flags_expired_contract():
    warnings = assert_no_survivorship_bias_in_contract_universe([CONTRACT], as_of=date(2022, 6, 1))
    assert len(warnings) == 1
    assert "expired" in warnings[0]


def test_survivorship_bias_guard_clean_for_valid_contract():
    warnings = assert_no_survivorship_bias_in_contract_universe([CONTRACT], as_of=date(2021, 12, 1))
    assert warnings == []
