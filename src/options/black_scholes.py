"""Phase 26, Part 7 — a minimal, standard Black-Scholes pricer and
implied-volatility solver.

This is generic, textbook option-pricing mathematics (Black & Scholes
1973 / Merton 1973), not a trading signal or an alpha source -- it
exists so this phase can do exactly what Part 7 asks ("if Greeks are not
supplied but can be deterministically reconstructed... classify them
separately as RECONSTRUCTABLE") on data sources (like Phase 26's real
QuantConnect/Lean sample) that carry no vendor-supplied IV/Greeks field
at all. `greeks.py` and `implied_volatility.py` (Phase 18) explicitly
left this solver unbuilt ("No IV solver ... is implemented in this
codebase as of this phase") -- this module is that solver, arriving only
once a real, concrete need for it (Part 7's reconstruction test) exists.

Every value this module produces MUST be attached to the existing
`DerivedIVMetadata`/`DerivedGreeksMetadata` provenance records (Phase
18) with `pricing_model="black_scholes"` -- never presented as an
OBSERVED/vendor-supplied value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

SOLVER_VERSION = "phase26_black_scholes_v1"


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


@dataclass(frozen=True)
class BlackScholesInputs:
    underlying_price: float
    strike: float
    time_to_expiration_years: float
    risk_free_rate: float
    volatility: float
    dividend_yield: float = 0.0

    def __post_init__(self):
        if self.underlying_price <= 0 or self.strike <= 0:
            raise ValueError("underlying_price and strike must be positive")
        if self.time_to_expiration_years <= 0:
            raise ValueError("time_to_expiration_years must be positive")
        if self.volatility <= 0:
            raise ValueError("volatility must be positive")

    def _d1(self) -> float:
        s, k, t, r, sigma, q = (self.underlying_price, self.strike, self.time_to_expiration_years,
                                 self.risk_free_rate, self.volatility, self.dividend_yield)
        return (math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))

    def _d2(self) -> float:
        return self._d1() - self.volatility * math.sqrt(self.time_to_expiration_years)


def black_scholes_price(inputs: BlackScholesInputs, *, call_put: str) -> float:
    s, k, t, r, q = (inputs.underlying_price, inputs.strike, inputs.time_to_expiration_years,
                     inputs.risk_free_rate, inputs.dividend_yield)
    d1, d2 = inputs._d1(), inputs._d2()
    disc_s = s * math.exp(-q * t)
    disc_k = k * math.exp(-r * t)
    if call_put == "call":
        return disc_s * _norm_cdf(d1) - disc_k * _norm_cdf(d2)
    if call_put == "put":
        return disc_k * _norm_cdf(-d2) - disc_s * _norm_cdf(-d1)
    raise ValueError(f"call_put must be 'call' or 'put', got {call_put!r}")


@dataclass(frozen=True)
class BlackScholesGreeks:
    delta: float
    gamma: float
    theta: float  # per calendar year; caller divides by 365 for per-day
    vega: float  # per 1.00 (100 percentage points) change in vol; caller divides by 100 for per-vol-point
    rho: float


def black_scholes_greeks(inputs: BlackScholesInputs, *, call_put: str) -> BlackScholesGreeks:
    s, k, t, r, sigma, q = (inputs.underlying_price, inputs.strike, inputs.time_to_expiration_years,
                             inputs.risk_free_rate, inputs.volatility, inputs.dividend_yield)
    d1, d2 = inputs._d1(), inputs._d2()
    pdf_d1 = _norm_pdf(d1)
    disc_q = math.exp(-q * t)
    disc_r = math.exp(-r * t)

    gamma = disc_q * pdf_d1 / (s * sigma * math.sqrt(t))
    vega = s * disc_q * pdf_d1 * math.sqrt(t)

    if call_put == "call":
        delta = disc_q * _norm_cdf(d1)
        theta = (-s * disc_q * pdf_d1 * sigma / (2 * math.sqrt(t)) - r * k * disc_r * _norm_cdf(d2)
                  + q * s * disc_q * _norm_cdf(d1))
        rho = k * t * disc_r * _norm_cdf(d2)
    elif call_put == "put":
        delta = -disc_q * _norm_cdf(-d1)
        theta = (-s * disc_q * pdf_d1 * sigma / (2 * math.sqrt(t)) + r * k * disc_r * _norm_cdf(-d2)
                  - q * s * disc_q * _norm_cdf(-d1))
        rho = -k * t * disc_r * _norm_cdf(-d2)
    else:
        raise ValueError(f"call_put must be 'call' or 'put', got {call_put!r}")

    return BlackScholesGreeks(delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho)


def implied_volatility_bisection(
    *, target_price: float, underlying_price: float, strike: float, time_to_expiration_years: float,
    risk_free_rate: float, dividend_yield: float, call_put: str,
    low: float = 1e-4, high: float = 5.0, tolerance: float = 1e-6, max_iterations: int = 100,
) -> float | None:
    """A plain bisection solver -- deterministic, no external
    dependency, adequate for a small certification sample (Part 7 does
    not ask for production-grade solver performance). Returns None
    (never a fabricated fallback number) if the target price is outside
    what any positive volatility can produce, or if convergence fails
    within `max_iterations`."""

    def price_at(vol: float) -> float:
        inputs = BlackScholesInputs(underlying_price, strike, time_to_expiration_years, risk_free_rate, vol, dividend_yield)
        return black_scholes_price(inputs, call_put=call_put)

    lo_price, hi_price = price_at(low), price_at(high)
    if not (lo_price <= target_price <= hi_price):
        return None

    for _ in range(max_iterations):
        mid = (low + high) / 2
        mid_price = price_at(mid)
        if abs(mid_price - target_price) < tolerance:
            return mid
        if mid_price < target_price:
            low = mid
        else:
            high = mid
    return (low + high) / 2
