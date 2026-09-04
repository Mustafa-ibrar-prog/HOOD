"""Phase 29, Part 6/17 — IV/Greeks consistency validation: vendor-
supplied vs. independently computed, using the real-value-reused AAPL
fixture (Phase 26's real 2015-01-02 close + a mid quote with a known
real Black-Scholes-implied IV)."""

from __future__ import annotations

from datetime import date

from src.options.orats_iv_greeks_certification import check_iv_greeks_consistency
from tests.orats_fixtures import SYNTHETIC_AAPL_REAL_VALUE_CROSSCHECK_ROW as ROW


def test_consistent_when_vendor_iv_matches_black_scholes_within_tolerance():
    mid = (ROW["callBidPrice"] + ROW["callAskPrice"]) / 2
    result = check_iv_greeks_consistency(
        contract_id="AAPL_call_100.0000_2016-01-15", vendor_iv=ROW["iv"], vendor_delta=ROW["delta"],
        mid_price=mid, underlying_price=ROW["underlyingPrice"], strike=ROW["strike"],
        expiration=date(2016, 1, 15), as_of=date(2015, 1, 2), call_put="call",
    )
    assert result.consistent is True
    assert result.iv_difference < 0.02
    assert result.delta_difference < 0.02


def test_independently_computed_iv_is_never_none_when_inputs_are_valid():
    mid = (ROW["callBidPrice"] + ROW["callAskPrice"]) / 2
    result = check_iv_greeks_consistency(
        contract_id="X", vendor_iv=ROW["iv"], vendor_delta=ROW["delta"],
        mid_price=mid, underlying_price=ROW["underlyingPrice"], strike=ROW["strike"],
        expiration=date(2016, 1, 15), as_of=date(2015, 1, 2), call_put="call",
    )
    assert result.independently_computed_iv is not None
    assert result.independently_computed_delta is not None


def test_inconsistent_when_vendor_iv_is_wildly_off():
    """A real, large disagreement must be surfaced, never hidden or
    silently marked consistent."""
    mid = (ROW["callBidPrice"] + ROW["callAskPrice"]) / 2
    result = check_iv_greeks_consistency(
        contract_id="X", vendor_iv=0.90, vendor_delta=ROW["delta"],  # a wildly wrong vendor IV
        mid_price=mid, underlying_price=ROW["underlyingPrice"], strike=ROW["strike"],
        expiration=date(2016, 1, 15), as_of=date(2015, 1, 2), call_put="call",
    )
    assert result.consistent is False
    assert result.iv_difference > 0.3


def test_returns_none_comparisons_when_expired():
    result = check_iv_greeks_consistency(
        contract_id="X", vendor_iv=0.3, vendor_delta=0.5,
        mid_price=5.0, underlying_price=100.0, strike=100.0,
        expiration=date(2015, 1, 1), as_of=date(2015, 1, 2), call_put="call",  # already expired relative to as_of
    )
    assert result.independently_computed_iv is None
    assert result.consistent is None


def test_never_raises_on_a_large_real_difference():
    """Part 6: differences are acceptable, never an exception."""
    mid = (ROW["callBidPrice"] + ROW["callAskPrice"]) / 2
    result = check_iv_greeks_consistency(
        contract_id="X", vendor_iv=5.0, vendor_delta=-3.0,  # nonsensical vendor values
        mid_price=mid, underlying_price=ROW["underlyingPrice"], strike=ROW["strike"],
        expiration=date(2016, 1, 15), as_of=date(2015, 1, 2), call_put="call",
    )
    assert result.consistent is False


def test_handles_missing_vendor_values_gracefully():
    mid = (ROW["callBidPrice"] + ROW["callAskPrice"]) / 2
    result = check_iv_greeks_consistency(
        contract_id="X", vendor_iv=None, vendor_delta=None,
        mid_price=mid, underlying_price=ROW["underlyingPrice"], strike=ROW["strike"],
        expiration=date(2016, 1, 15), as_of=date(2015, 1, 2), call_put="call",
    )
    assert result.iv_difference is None
    assert result.consistent is None
