"""Phase 18, Part 22 — option instrument parsing, contract identity,
strike, call/put, multiplier, corporate-action deliverable tests."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.options.instrument import OptionContract


def _contract(**overrides) -> OptionContract:
    defaults = dict(underlying_symbol="AAPL", option_id="c55a630e-a0b9-45ab-b889-47bee291fee7", call_put="call", strike=175.0, expiration=date(2022, 1, 21))
    defaults.update(overrides)
    return OptionContract(**defaults)


def test_real_contract_construction():
    c = _contract()
    assert c.underlying_symbol == "AAPL"
    assert c.contract_multiplier == 100
    assert c.exercise_style is None
    assert c.settlement_type is None


def test_occ_style_description():
    c = _contract()
    assert c.occ_style_description == "AAPL 2022-01-21 C 175"


def test_put_description():
    c = _contract(call_put="put", strike=25.0)
    assert c.occ_style_description == "AAPL 2022-01-21 P 25"


def test_invalid_call_put_rejected():
    with pytest.raises(ValueError):
        _contract(call_put="straddle")


def test_invalid_strike_rejected():
    with pytest.raises(ValueError):
        _contract(strike=0)
    with pytest.raises(ValueError):
        _contract(strike=-10)


def test_invalid_multiplier_rejected():
    with pytest.raises(ValueError):
        _contract(contract_multiplier=0)


def test_contract_identity_by_option_id():
    a = _contract()
    b = _contract()
    assert a == b  # same fields -> equal, frozen dataclass


def test_non_standard_deliverable_requires_note():
    with pytest.raises(ValueError):
        _contract(is_standard_deliverable=False)  # no deliverable_note


def test_non_standard_deliverable_with_note_is_valid():
    c = _contract(contract_multiplier=300, is_standard_deliverable=False, deliverable_note="adjusted for 2022-08-25 3:1 split, 300 shares/contract")
    assert c.contract_multiplier == 300
    assert c.deliverable_note is not None


def test_unknown_exercise_and_settlement_are_none_never_guessed():
    """Confirmed: exercise_style/settlement_type are NEVER supplied by
    this source -- must stay None by default, not default to a guessed
    'american'/'physical'."""
    c = _contract()
    assert c.exercise_style is None
    assert c.settlement_type is None


def test_retrieval_timestamp_optional():
    c = _contract(retrieval_timestamp=datetime(2026, 9, 3, tzinfo=timezone.utc))
    assert c.retrieval_timestamp is not None
    c2 = _contract()
    assert c2.retrieval_timestamp is None
