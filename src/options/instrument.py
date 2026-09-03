"""Phase 18, Part 2 — the canonical options instrument (contract) model.

Fields are populated only from what a source ACTUALLY supplies. Confirmed
real fields (get_option_instruments, real probe against AAPL contracts
spanning 2017-2026, both active and expired/state="expired"): id
(instrument UUID), chain_id, chain_symbol, underlying_type ("equity" |
"index"), expiration_date, strike_price, type ("call"|"put"), state
("active"|"expired"|"inactive"), tradability, trade_value_multiplier
(observed "100.0000" for every contract probed — see Part 15's corporate-
action note below), min_ticks, sellout_datetime.

NOT supplied by this source (confirmed absent from every real response
probed): exercise_style (American/European), settlement_type (physical/
cash). Both stay None — never guessed as "American" just because that's
the norm for US single-stock equity options; a genuinely correct default
would need to come from the source, not an assumption.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class OptionContract:
    """One options contract's identity. Two contracts are the same
    contract iff `option_id` matches — every other field is descriptive,
    not part of identity (an issuer can't have two contracts with the
    same id and different strikes)."""

    underlying_symbol: str
    option_id: str  # source instrument UUID (get_option_instruments' "id")
    call_put: str  # "call" | "put"
    strike: float
    expiration: date
    contract_multiplier: int = 100  # confirmed via real probe: every contract observed reports trade_value_multiplier="100.0000"
    exercise_style: str | None = None  # "american" | "european" | None=unknown -- NEVER supplied by this source, confirmed
    settlement_type: str | None = None  # "physical" | "cash" | None=unknown -- NEVER supplied by this source, confirmed
    currency: str = "USD"
    is_standard_deliverable: bool = True  # Part 15: False for a corporate-action-adjusted contract (non-100 multiplier or non-share deliverable)
    deliverable_note: str | None = None  # Part 15: e.g. "adjusted for 2022-08-25 3:1 split, 300 shares/contract" -- required when is_standard_deliverable=False
    source: str = "mcp__HOOD__get_option_instruments"
    retrieval_timestamp: datetime | None = None
    schema_version: str = "options-v1"

    def __post_init__(self) -> None:
        if self.call_put not in ("call", "put"):
            raise ValueError(f"call_put must be 'call' or 'put', got {self.call_put!r}")
        if self.strike <= 0:
            raise ValueError(f"strike must be > 0, got {self.strike}")
        if self.contract_multiplier <= 0:
            raise ValueError(f"contract_multiplier must be > 0, got {self.contract_multiplier}")
        if not self.is_standard_deliverable and not self.deliverable_note:
            raise ValueError("a non-standard deliverable must document why via deliverable_note (Part 15 -- no unexplained adjustments)")

    @property
    def occ_style_description(self) -> str:
        """Human-readable identity, e.g. 'AAPL 2026-09-18 C 230.0' --
        mirrors the real occ_symbol format confirmed via
        get_option_historicals (e.g. 'AAPL  220121P00025000')."""
        side = "C" if self.call_put == "call" else "P"
        return f"{self.underlying_symbol} {self.expiration.isoformat()} {side} {self.strike:g}"
