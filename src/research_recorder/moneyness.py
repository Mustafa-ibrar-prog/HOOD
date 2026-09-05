"""Phase 37, Part 17 — moneyness, computed only from the underlying
price observed AT THE SAME OBSERVATION TIMESTAMP (never a later price).

Stores the exact underlying price used and a version string so a future
researcher can tell exactly how a given moneyness value was derived,
and re-derive it if the formula ever changes.
"""

from __future__ import annotations

from dataclasses import dataclass

MONEYNESS_VERSION = "phase37-moneyness-v1"  # (underlying_price - strike) / underlying_price for calls; (strike - underlying_price) / underlying_price for puts


@dataclass(frozen=True)
class MoneynessResult:
    moneyness: float | None  # None when strike or underlying_price is missing -- never guessed
    underlying_price_used: float | None
    strike_used: float | None
    version: str = MONEYNESS_VERSION


def compute_moneyness(*, underlying_price: float | None, strike: float | None, option_type: str | None) -> MoneynessResult:
    if underlying_price is None or strike is None or underlying_price <= 0:
        return MoneynessResult(None, underlying_price, strike)
    if option_type == "put":
        value = (strike - underlying_price) / underlying_price
    else:  # "call" or unknown -- the call convention is the documented default when option_type is itself missing
        value = (underlying_price - strike) / underlying_price
    return MoneynessResult(value, underlying_price, strike)
