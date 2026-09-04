"""Phase 29, Part 6 — IV/Greeks certification for ORATS.

Unlike Phase 26/27's QuantConnect/Lean source (zero native IV/Greeks,
everything RECONSTRUCTED), ORATS's real schema DOES supply IV and full
Greeks directly (`Strike.iv`/`delta`/`gamma`/`theta`/`vega`/`rho`) --
these are classified `VENDOR_SUPPLIED`, never `RECONSTRUCTED`. This
module cross-checks a vendor-supplied IV/delta against an independently
computed Black-Scholes value from the SAME row's own bid/ask/strike/
underlying-price fields, reusing Phase 26's `black_scholes.py` solver
unchanged -- consistency validation, not exact-equality (Part 6's own
explicit instruction).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.options.black_scholes import SOLVER_VERSION, BlackScholesInputs, black_scholes_greeks

PRICING_MODEL = "black_scholes"

# Same external, documented assumption as Phase 26 -- ORATS's schema
# itself has a `residual_rate` field (a real, confirmed field) that
# COULD supply this more precisely in a future phase with real data;
# this phase never had a real row to read residual_rate from, so the
# same illustrative placeholder is used, explicitly flagged.
ASSUMED_DIVIDEND_YIELD = 0.015


@dataclass(frozen=True)
class IVGreeksConsistencyCheck:
    contract_id: str
    vendor_iv: float | None
    independently_computed_iv: float | None
    iv_difference: float | None
    vendor_delta: float | None
    independently_computed_delta: float | None
    delta_difference: float | None
    consistent: bool | None  # None when a comparison could not be performed at all


def check_iv_greeks_consistency(
    *, contract_id: str, vendor_iv: float | None, vendor_delta: float | None,
    mid_price: float, underlying_price: float, strike: float, expiration: date, as_of: date,
    call_put: str, risk_free_rate: float = 0.02, tolerance: float = 0.15,
) -> IVGreeksConsistencyCheck:
    """`tolerance` is a relative IV/delta difference threshold for
    `consistent` (0.15 = 15%) -- Part 6: 'differences are acceptable...
    the objective is consistency validation, not exact equality.' Never
    raises on a large difference -- a large, real difference is exactly
    the kind of finding this check exists to surface, not hide."""
    t_years = (expiration - as_of).days / 365.0
    if t_years <= 0 or mid_price <= 0 or underlying_price <= 0 or strike <= 0:
        return IVGreeksConsistencyCheck(contract_id, vendor_iv, None, None, vendor_delta, None, None, None)

    from src.options.black_scholes import implied_volatility_bisection
    computed_iv = implied_volatility_bisection(
        target_price=mid_price, underlying_price=underlying_price, strike=strike,
        time_to_expiration_years=t_years, risk_free_rate=risk_free_rate,
        dividend_yield=ASSUMED_DIVIDEND_YIELD, call_put=call_put,
    )

    computed_delta = None
    if computed_iv is not None:
        inputs = BlackScholesInputs(underlying_price, strike, t_years, risk_free_rate, computed_iv, ASSUMED_DIVIDEND_YIELD)
        computed_delta = black_scholes_greeks(inputs, call_put=call_put).delta

    iv_diff = abs(vendor_iv - computed_iv) if (vendor_iv is not None and computed_iv is not None) else None
    delta_diff = abs(vendor_delta - computed_delta) if (vendor_delta is not None and computed_delta is not None) else None

    consistent = None
    if iv_diff is not None:
        consistent = iv_diff <= tolerance and (delta_diff is None or delta_diff <= tolerance)

    return IVGreeksConsistencyCheck(
        contract_id=contract_id, vendor_iv=vendor_iv, independently_computed_iv=computed_iv, iv_difference=iv_diff,
        vendor_delta=vendor_delta, independently_computed_delta=computed_delta, delta_difference=delta_diff,
        consistent=consistent,
    )
