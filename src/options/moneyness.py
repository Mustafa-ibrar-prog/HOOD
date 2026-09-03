"""Phase 19, Part 5 — causal option moneyness.

Moneyness at bar i is computed from ONLY the underlying's close at bar i
and the contract's fixed strike -- never from a future underlying price,
never from the contract's own option price (which already embeds
time-value/IV information moneyness is meant to be independent of). This
is what makes it "causal": an observer standing at bar i, knowing only
what happened up to and including bar i, could compute the exact same
number.

Method choice, documented explicitly (Part 5 requires this): log-
moneyness `ln(S/K)` is used as the primary continuous measure (standard
in options research -- symmetric around 0, and additive across
maturities, unlike the raw ratio S/K). The raw ratio `S/K` is also
recorded alongside it (simpler to read, some readers prefer it) but is
NOT used for bucketing -- log-moneyness is. Call and put moneyness use
the SAME sign convention (ln(S/K) > 0 means the underlying trades above
the strike) -- "in the money" therefore means opposite bucket directions
for calls vs puts, handled explicitly in `classify_moneyness` rather than
folded into the log-moneyness formula itself.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass


class MoneynessBucket(enum.Enum):
    DEEP_ITM = "deep_itm"
    ITM = "itm"
    NEAR_ATM = "near_atm"
    OTM = "otm"
    DEEP_OTM = "deep_otm"


# Bucket edges on |log_moneyness|, chosen before any Phase 19 discovery
# result was seen (Part 8 preregistration discipline): NEAR_ATM within
# +/-2%, ITM/OTM out to +/-15%, DEEP beyond that. Applied to a CALL's
# raw sign (ln(S/K) > 0 => call is ITM); a PUT's classification uses the
# negated sign (ln(S/K) < 0 => put is ITM) since a put is in the money
# when the underlying is BELOW the strike.
_NEAR_ATM_EDGE = 0.02
_ITM_OTM_EDGE = 0.15


def log_moneyness(underlying_price: float, strike: float) -> float:
    if underlying_price <= 0 or strike <= 0:
        raise ValueError(f"underlying_price ({underlying_price}) and strike ({strike}) must both be > 0")
    return math.log(underlying_price / strike)


def moneyness_ratio(underlying_price: float, strike: float) -> float:
    if strike <= 0:
        raise ValueError(f"strike must be > 0, got {strike}")
    return underlying_price / strike


def classify_moneyness(underlying_price: float, strike: float, call_put: str) -> MoneynessBucket:
    if call_put not in ("call", "put"):
        raise ValueError(f"call_put must be 'call' or 'put', got {call_put!r}")
    lm = log_moneyness(underlying_price, strike)
    signed = lm if call_put == "call" else -lm  # positive => in the money, for either type
    magnitude = abs(lm)
    if magnitude <= _NEAR_ATM_EDGE:
        return MoneynessBucket.NEAR_ATM
    if signed > 0:
        return MoneynessBucket.ITM if magnitude <= _ITM_OTM_EDGE else MoneynessBucket.DEEP_ITM
    return MoneynessBucket.OTM if magnitude <= _ITM_OTM_EDGE else MoneynessBucket.DEEP_OTM


@dataclass(frozen=True)
class MoneynessObservation:
    underlying_price: float
    strike: float
    call_put: str
    log_moneyness_value: float
    moneyness_ratio_value: float
    bucket: MoneynessBucket

    @classmethod
    def compute(cls, *, underlying_price: float, strike: float, call_put: str) -> "MoneynessObservation":
        return cls(
            underlying_price=underlying_price, strike=strike, call_put=call_put,
            log_moneyness_value=log_moneyness(underlying_price, strike),
            moneyness_ratio_value=moneyness_ratio(underlying_price, strike),
            bucket=classify_moneyness(underlying_price, strike, call_put),
        )
