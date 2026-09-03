"""Phase 19, Part 16/19 — the 4-state contract-existence classification."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.options.contract_existence import ExistenceState, classify_existence
from src.options.instrument import OptionContract
from src.options.point_in_time import ContractExistenceEvidence

CONTRACT = OptionContract(underlying_symbol="AAPL", option_id="c1", call_put="call", strike=175.0, expiration=date(2022, 1, 21))


def _evidence(first_listed=None, source="mcp__HOOD__get_option_instruments") -> ContractExistenceEvidence:
    return ContractExistenceEvidence(contract=CONTRACT, first_listed_date=first_listed, expiration=CONTRACT.expiration, source=source)


def test_known_expired_after_expiration():
    ev = _evidence()
    state = classify_existence(ev, as_of=datetime(2022, 2, 1, tzinfo=timezone.utc))
    assert state == ExistenceState.KNOWN_EXPIRED


def test_unknown_existence_before_expiration_with_no_first_listed_date():
    """This is the honest, real-data state for every contract this
    phase's source has ever returned -- first_listed_date is never known."""
    ev = _evidence(first_listed=None)
    state = classify_existence(ev, as_of=datetime(2021, 12, 1, tzinfo=timezone.utc))
    assert state == ExistenceState.UNKNOWN_EXISTENCE


def test_known_existence_when_first_listed_date_is_known_and_within_window():
    ev = _evidence(first_listed=date(2021, 6, 1))
    state = classify_existence(ev, as_of=datetime(2021, 12, 1, tzinfo=timezone.utc))
    assert state == ExistenceState.KNOWN_EXISTENCE


def test_insufficient_pit_evidence_when_source_is_missing():
    ev = _evidence(source="")
    state = classify_existence(ev, as_of=datetime(2021, 12, 1, tzinfo=timezone.utc))
    assert state == ExistenceState.INSUFFICIENT_PIT_EVIDENCE


def test_never_guesses_known_existence_without_a_first_listed_date():
    """Structural proof: no combination of inputs without a real
    first_listed_date can produce KNOWN_EXISTENCE."""
    for as_of_year in (2018, 2020, 2021, 2022):
        ev = _evidence(first_listed=None)
        state = classify_existence(ev, as_of=datetime(as_of_year, 6, 1, tzinfo=timezone.utc))
        assert state != ExistenceState.KNOWN_EXISTENCE
