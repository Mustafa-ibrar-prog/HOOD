"""Phase 37, Part 7-9 — raw payload preservation, fingerprinting, and
normalized-observation provenance."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.research_recorder.normalized_observation import (
    build_normalized_option_observation,
    build_normalized_underlying_observation,
)
from src.research_recorder.provenance import LiveObservationProvenance
from src.research_recorder.raw_observation import RawObservation, fingerprint_payload


def _now():
    return datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc)


# --- Raw observation / fingerprinting -----------------------------------------------------------


def test_fingerprint_is_deterministic_regardless_of_key_order():
    a = fingerprint_payload({"x": 1, "y": 2})
    b = fingerprint_payload({"y": 2, "x": 1})
    assert a == b


def test_fingerprint_differs_for_different_content():
    assert fingerprint_payload({"x": 1}) != fingerprint_payload({"x": 2})


def test_raw_observation_rejects_a_mismatched_fingerprint():
    with pytest.raises(ValueError):
        RawObservation(
            observation_cycle_id="c1", provider="robinhood_hood_mcp", tool_name="get_option_quotes",
            retrieval_timestamp=_now(), market_timestamp=None, raw_payload={"a": 1}, payload_fingerprint="wrong",
        )


def test_raw_observation_build_computes_a_correct_fingerprint():
    obs = RawObservation.build(
        observation_cycle_id="c1", provider="robinhood_hood_mcp", tool_name="get_option_quotes",
        retrieval_timestamp=_now(), market_timestamp=None, raw_payload={"a": 1},
    )
    assert obs.payload_fingerprint == fingerprint_payload({"a": 1})


def test_raw_observation_round_trips_through_dict():
    obs = RawObservation.build(
        observation_cycle_id="c1", provider="robinhood_hood_mcp", tool_name="get_option_quotes",
        retrieval_timestamp=_now(), market_timestamp=_now(), raw_payload={"a": 1}, request_context={"symbol": "AAPL"},
    )
    restored = RawObservation.from_dict(obs.to_dict())
    assert restored == obs


def test_raw_observation_is_immutable():
    obs = RawObservation.build(
        observation_cycle_id="c1", provider="robinhood_hood_mcp", tool_name="get_option_quotes",
        retrieval_timestamp=_now(), market_timestamp=None, raw_payload={"a": 1},
    )
    with pytest.raises(Exception):
        obs.raw_payload = {"a": 2}  # type: ignore[misc]


# --- Normalized observation provenance -----------------------------------------------------------


def test_underlying_observation_missing_row_marks_every_field_missing():
    obs = build_normalized_underlying_observation(symbol="AAPL", observation_cycle_id="c1", observation_timestamp=_now(), quote_row=None)
    assert obs.bid is None and obs.ask is None and obs.last is None
    assert all(v == LiveObservationProvenance.MISSING.value for v in obs.field_provenance.values())


def test_underlying_observation_present_fields_marked_live():
    row = {"bid_price": "1.0", "ask_price": "1.05", "last_trade_price": "230.0", "volume": "1000"}
    obs = build_normalized_underlying_observation(symbol="AAPL", observation_cycle_id="c1", observation_timestamp=_now(), quote_row=row)
    assert obs.field_provenance["bid"] == LiveObservationProvenance.LIVE.value
    assert obs.field_provenance["midpoint"] == LiveObservationProvenance.DERIVED_FROM_LIVE.value


def test_option_observation_never_fabricates_bid_size_or_greeks_when_absent():
    obs = build_normalized_option_observation(
        option_id="opt-1", underlying="AAPL", observation_cycle_id="c1", observation_timestamp=_now(),
        market_timezone="America/New_York", quote_row={"bid_price": "1.0", "ask_price": "1.05"},
        chain_row={"type": "call", "strike_price": "230.0", "expiration_date": "2026-10-01", "state": "active", "tradability": "tradable"},
        underlying_price=230.0,
    )
    assert obs.bid_size is None
    assert obs.implied_volatility is None
    assert obs.field_provenance["bid_size"] == LiveObservationProvenance.MISSING.value
    assert obs.field_provenance["implied_volatility"] == LiveObservationProvenance.MISSING.value


def test_option_observation_parses_greeks_and_sizes_when_present():
    obs = build_normalized_option_observation(
        option_id="opt-1", underlying="AAPL", observation_cycle_id="c1", observation_timestamp=_now(),
        market_timezone="America/New_York",
        quote_row={
            "bid_price": "1.0", "ask_price": "1.05", "bid_size": "5", "ask_size": "7", "implied_volatility": "0.3",
            "delta": "0.5", "gamma": "0.01", "theta": "-0.02", "vega": "0.03", "rho": "0.01",
            "break_even_price": "231.05", "chance_of_profit_long": "0.4", "chance_of_profit_short": "0.6",
        },
        chain_row={"type": "call", "strike_price": "230.0", "expiration_date": "2026-10-01", "state": "active", "tradability": "tradable"},
        underlying_price=230.0,
    )
    assert obs.bid_size == 5 and obs.ask_size == 7
    assert obs.implied_volatility == 0.3 and obs.delta == 0.5
    assert obs.break_even == 231.05
    assert obs.chance_of_profit_long == 0.4 and obs.chance_of_profit_short == 0.6
    assert obs.field_provenance["bid_size"] == LiveObservationProvenance.LIVE.value


def test_option_observation_last_trade_always_missing_documented():
    """Options have no true last-trade field (mark_price is used
    instead) -- always None, WITH an explicit MISSING provenance entry,
    never silently omitted from the record."""
    obs = build_normalized_option_observation(
        option_id="opt-1", underlying="AAPL", observation_cycle_id="c1", observation_timestamp=_now(),
        market_timezone="America/New_York", quote_row={"bid_price": "1.0", "ask_price": "1.05"},
        chain_row={"type": "call", "strike_price": "230.0", "expiration_date": "2026-10-01"}, underlying_price=230.0,
    )
    assert obs.last_trade is None
    assert "last_trade" in obs.field_provenance
    assert obs.field_provenance["last_trade"] == LiveObservationProvenance.MISSING.value


def test_option_observation_missing_chain_row_marks_contract_fields_missing():
    obs = build_normalized_option_observation(
        option_id="opt-1", underlying="AAPL", observation_cycle_id="c1", observation_timestamp=_now(),
        market_timezone="America/New_York", quote_row=None, chain_row=None, underlying_price=None,
    )
    assert obs.option_type is None and obs.strike is None and obs.expiration is None
    assert obs.dte is None
    assert obs.field_provenance["option_type"] == LiveObservationProvenance.MISSING.value
    assert obs.field_provenance["dte"] == LiveObservationProvenance.MISSING.value


def test_option_observation_dte_and_moneyness_are_derived_from_live():
    obs = build_normalized_option_observation(
        option_id="opt-1", underlying="AAPL", observation_cycle_id="c1", observation_timestamp=_now(),
        market_timezone="America/New_York", quote_row={"bid_price": "1.0", "ask_price": "1.05"},
        chain_row={"type": "call", "strike_price": "230.0", "expiration_date": "2026-10-01"}, underlying_price=230.0,
    )
    assert obs.field_provenance["dte"] == LiveObservationProvenance.DERIVED_FROM_LIVE.value
    assert obs.field_provenance["moneyness"] == LiveObservationProvenance.DERIVED_FROM_LIVE.value
