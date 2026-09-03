"""Phase 18, Part 22 — Greeks representation and IV representation
tests: observed vs derived vs unavailable, never pretending derived is
observed."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.options.greeks import DerivedGreeksMetadata, Greeks, GreeksProvenance
from src.options.implied_volatility import DerivedIVMetadata, IVObservation, IVProvenance


def test_observed_greeks_real_values():
    # Real, transcribed from an actual get_option_quotes probe.
    g = Greeks.observed(delta=0.982989, gamma=0.000756, theta=-0.097964, vega=0.028455, rho=0.096388)
    assert g.provenance == GreeksProvenance.OBSERVED_FROM_SOURCE
    assert g.derived_metadata is None


def test_unavailable_greeks():
    g = Greeks.unavailable()
    assert g.provenance == GreeksProvenance.UNAVAILABLE
    assert g.delta is None


def test_derived_greeks_require_metadata():
    with pytest.raises(ValueError):
        Greeks(delta=0.5, provenance=GreeksProvenance.DERIVED_FROM_MODEL)  # no derived_metadata


def test_derived_greeks_with_metadata_valid():
    meta = DerivedGreeksMetadata(model="black_scholes", inputs={"S": 175.0}, timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), volatility_input=0.3, rate_assumption=0.04, dividend_assumption=0.0, version="v1")
    g = Greeks(delta=0.5, provenance=GreeksProvenance.DERIVED_FROM_MODEL, derived_metadata=meta)
    assert g.derived_metadata is meta


def test_observed_greeks_cannot_carry_derived_metadata():
    meta = DerivedGreeksMetadata(model="black_scholes", inputs={}, timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), volatility_input=0.3, rate_assumption=0.04, dividend_assumption=0.0, version="v1")
    with pytest.raises(ValueError):
        Greeks(delta=0.5, provenance=GreeksProvenance.OBSERVED_FROM_SOURCE, derived_metadata=meta)


def test_observed_iv_real_value():
    iv = IVObservation.observed(0.822619)
    assert iv.provenance == IVProvenance.OBSERVED
    assert iv.value == 0.822619


def test_unavailable_iv():
    iv = IVObservation.unavailable()
    assert iv.provenance == IVProvenance.UNAVAILABLE
    assert iv.value is None


def test_negative_iv_rejected():
    with pytest.raises(ValueError):
        IVObservation(value=-0.1, provenance=IVProvenance.OBSERVED)


def test_derived_iv_requires_metadata():
    with pytest.raises(ValueError):
        IVObservation(value=0.3, provenance=IVProvenance.DERIVED)


def test_derived_iv_with_metadata_valid():
    meta = DerivedIVMetadata(
        pricing_model="black_scholes", option_price_used=3.53, underlying_price=170.0, strike=175.0,
        expiration=date(2022, 1, 21), time_to_expiration_years=0.14, interest_rate=0.01, dividend_assumption=0.0,
        solver_version="v1", timestamp=datetime(2021, 12, 1, tzinfo=timezone.utc),
    )
    iv = IVObservation(value=0.35, provenance=IVProvenance.DERIVED, derived_metadata=meta)
    assert iv.derived_metadata is meta
