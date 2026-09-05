"""Phase 36, Part 9 — option contract validation before a decision
reaches risk.

Explicit rejection codes, never a bare boolean and never an invented
price. This runs BEFORE `risk_handoff.py` -- risk's own `check_spread`/
`check_liquidity` (src/risk/manager.py) assume a contract that already
identifies itself correctly; this module is what catches "this isn't
even a real, current, tradable contract" before risk ever sees it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from src.production.live_snapshot import OptionLiveState


class ContractRejectionCode(str, Enum):
    MISSING_OPTION_ID = "MISSING_OPTION_ID"
    CONTRACT_NOT_FOUND = "CONTRACT_NOT_FOUND"  # no live quote/state could be obtained for this option_id at all
    EXPIRED = "EXPIRED"
    INACTIVE = "INACTIVE"  # state != "active"
    NOT_TRADABLE = "NOT_TRADABLE"  # tradability != "tradable"
    INVALID_PRICE = "INVALID_PRICE"  # a required price field is missing/non-positive
    ZERO_OR_CROSSED_MARKET = "ZERO_OR_CROSSED_MARKET"  # bid/ask both present but crossed or both zero
    STALE_QUOTE = "STALE_QUOTE"
    MISSING_UNDERLYING = "MISSING_UNDERLYING"


@dataclass(frozen=True)
class ContractValidationResult:
    option_id: str | None
    passed: bool
    rejection_code: ContractRejectionCode | None
    message: str


def validate_option_contract(
    option: OptionLiveState | None,
    *,
    now: datetime,
    max_quote_age_seconds: float,
    today: date | None = None,
) -> ContractValidationResult:
    """Never invents a price or a status -- every rejection here is a
    direct read of a real (possibly missing) field on `option`."""
    today = today or now.date()

    if option is None:
        return ContractValidationResult(None, False, ContractRejectionCode.MISSING_OPTION_ID, "No option contract provided")
    if not option.option_id:
        return ContractValidationResult(option.option_id, False, ContractRejectionCode.MISSING_OPTION_ID, "option_id is missing/empty")
    if not option.underlying:
        return ContractValidationResult(option.option_id, False, ContractRejectionCode.MISSING_UNDERLYING, "underlying symbol is missing")
    if option.expiration is not None and option.expiration < today:
        return ContractValidationResult(option.option_id, False, ContractRejectionCode.EXPIRED, f"Contract expired on {option.expiration.isoformat()}")
    if option.state is not None and option.state != "active":
        return ContractValidationResult(option.option_id, False, ContractRejectionCode.INACTIVE, f"Contract state is {option.state!r}, not 'active'")
    if option.tradability is not None and option.tradability != "tradable":
        return ContractValidationResult(option.option_id, False, ContractRejectionCode.NOT_TRADABLE, f"Contract tradability is {option.tradability!r}, not 'tradable'")

    if option.timestamp is None:
        return ContractValidationResult(option.option_id, False, ContractRejectionCode.CONTRACT_NOT_FOUND, "No live quote timestamp -- contract could not be confirmed live")
    age = (now - option.timestamp).total_seconds()
    if age > max_quote_age_seconds:
        return ContractValidationResult(option.option_id, False, ContractRejectionCode.STALE_QUOTE, f"Quote is {age:.0f}s old (limit {max_quote_age_seconds:.0f}s)")

    if option.bid is None or option.ask is None:
        return ContractValidationResult(option.option_id, False, ContractRejectionCode.INVALID_PRICE, "Missing bid/ask")
    if option.bid < 0 or option.ask < 0:
        return ContractValidationResult(option.option_id, False, ContractRejectionCode.INVALID_PRICE, f"Negative price (bid={option.bid}, ask={option.ask})")
    if option.ask < option.bid or (option.bid == 0 and option.ask == 0):
        return ContractValidationResult(option.option_id, False, ContractRejectionCode.ZERO_OR_CROSSED_MARKET, f"Crossed or zero market (bid={option.bid}, ask={option.ask})")

    return ContractValidationResult(option.option_id, True, None, "Contract passes all validation checks")
