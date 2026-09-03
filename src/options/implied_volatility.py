"""Phase 18, Part 13 — implied volatility architecture.

Confirmed real: a live get_option_quotes response includes
implied_volatility directly (real probe: 0.822619 for a AAPL $230C
2026-09-18 contract). This is OBSERVED when it comes from that response.
Confirmed absent from get_option_historicals (no IV field in a
historical bar) -- IV is LIVE-ONLY via this connector, exactly like
Greeks (greeks.py).

No IV solver (Black-Scholes inversion or otherwise) is implemented in
this codebase as of this phase (Part 19: "Do not silently estimate
IV"). This module defines the SCHEMA for representing IV once observed
or derived; nothing here computes one.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, datetime


class IVProvenance(enum.Enum):
    OBSERVED = "observed"  # came directly from a real quote response
    DERIVED = "derived"  # solved from an option price via a pricing model -- must carry DerivedIVMetadata
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class DerivedIVMetadata:
    """Required whenever provenance == DERIVED (Part 13: 'record pricing
    model, option price used, underlying price, strike, time to
    expiration, interest rate, dividend assumption, solver/version,
    timestamp'). Never constructed by this phase's code -- no solver
    exists yet."""

    pricing_model: str
    option_price_used: float
    underlying_price: float
    strike: float
    expiration: date
    time_to_expiration_years: float
    interest_rate: float
    dividend_assumption: float
    solver_version: str
    timestamp: datetime


@dataclass(frozen=True)
class IVObservation:
    value: float | None = None
    provenance: IVProvenance = IVProvenance.UNAVAILABLE
    derived_metadata: DerivedIVMetadata | None = None

    def __post_init__(self) -> None:
        if self.provenance == IVProvenance.DERIVED and self.derived_metadata is None:
            raise ValueError("DERIVED IV must carry derived_metadata -- never pretend a derived value is observed")
        if self.provenance == IVProvenance.OBSERVED and self.derived_metadata is not None:
            raise ValueError("OBSERVED IV must not carry derived_metadata")
        if self.value is not None and self.value < 0:
            raise ValueError(f"IV cannot be negative, got {self.value}")

    @classmethod
    def observed(cls, value: float) -> "IVObservation":
        return cls(value=value, provenance=IVProvenance.OBSERVED)

    @classmethod
    def unavailable(cls) -> "IVObservation":
        return cls(provenance=IVProvenance.UNAVAILABLE)
