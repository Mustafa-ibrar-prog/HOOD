"""Phase 18, Part 12 — Greeks architecture.

Confirmed real: a live get_option_quotes response includes delta, gamma,
theta, vega, rho directly (real probe, AAPL $230C 2026-09-18: delta=
0.982989, gamma=0.000756, theta=-0.097964, vega=0.028455, rho=0.096388).
These are OBSERVED_FROM_SOURCE when they come from that response.
Confirmed absent from get_option_historicals (no Greeks field of any
kind in a historical bar) -- so Greeks are LIVE-ONLY, exactly like the
rest of get_option_quotes.

No Greeks computation (Black-Scholes or otherwise) is implemented in
this codebase as of this phase -- this module defines the SCHEMA for
representing Greeks once observed or derived, not a pricing model. A
future phase that adds a real solver populates DerivedGreeksMetadata;
nothing here fabricates one.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime


class GreeksProvenance(enum.Enum):
    OBSERVED_FROM_SOURCE = "observed_from_source"  # came directly from a real quote response
    DERIVED_FROM_MODEL = "derived_from_model"  # computed by a pricing model -- must carry DerivedGreeksMetadata
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class DerivedGreeksMetadata:
    """Required whenever provenance == DERIVED_FROM_MODEL (Part 12: 'If
    Greeks are derived: record model, inputs, timestamp, volatility
    input, rate assumption, dividend assumption, version'). Never
    constructed by this phase's code -- no solver exists yet."""

    model: str  # e.g. "black_scholes"
    inputs: dict[str, float]
    timestamp: datetime
    volatility_input: float
    rate_assumption: float
    dividend_assumption: float
    version: str


@dataclass(frozen=True)
class Greeks:
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None
    provenance: GreeksProvenance = GreeksProvenance.UNAVAILABLE
    derived_metadata: DerivedGreeksMetadata | None = None

    def __post_init__(self) -> None:
        if self.provenance == GreeksProvenance.DERIVED_FROM_MODEL and self.derived_metadata is None:
            raise ValueError("DERIVED_FROM_MODEL Greeks must carry derived_metadata -- never pretend a derived value is observed")
        if self.provenance == GreeksProvenance.OBSERVED_FROM_SOURCE and self.derived_metadata is not None:
            raise ValueError("OBSERVED_FROM_SOURCE Greeks must not carry derived_metadata -- that would mix observed and derived provenance")

    @classmethod
    def observed(cls, *, delta: float | None, gamma: float | None, theta: float | None, vega: float | None, rho: float | None) -> "Greeks":
        return cls(delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho, provenance=GreeksProvenance.OBSERVED_FROM_SOURCE)

    @classmethod
    def unavailable(cls) -> "Greeks":
        return cls(provenance=GreeksProvenance.UNAVAILABLE)
