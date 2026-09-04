"""Phase 29, Part 1 — the ORATS adapter's per-field provenance table.

Every field is classified using Part 1's exact 4-value vocabulary
(`VENDOR_SUPPLIED`/`RECONSTRUCTED`/`DERIVED`/`UNAVAILABLE`). Built from
the same real, independently-fetched open-source client schema evidence
Phase 25 gathered (`FyZyX/orats-python`,
`src/orats/constructs/api/data.py`'s `Strike`/`Ticker`/`Money`/
`HistoricalVolatility`/`DividendHistory`/`StockSplitHistory`/
`EarningsHistory` classes) -- never a live API call (none was ever made
any phase; `ORATS_ACTIVATION_PENDING_HUMAN`, see orats_activation_state.py).

SELF-CORRECTION (found while building this table): Phase 28's
`ORATS_SCORECARD` originally scored `QUOTE_SIZES` at 1/5 with the
rationale "no bid/ask SIZE field observed anywhere in the fetched
schema." Re-reading the exact, verbatim schema this project fetched in
Phase 25 while building this table found that claim was WRONG --
`Strike.call_bid_size`/`call_ask_size`/`put_bid_size`/`put_ask_size` ARE
real, confirmed fields in the schema this project already had. Phase 28's
`ORATS_SCORECARD`/`ORATS_STRONGEST_DIMENSIONS`/`RANKING` rationale text
has been corrected in place (`phase28_provider_scorecard.py`,
`phase28_provider_decision.py`) -- ORATS's total moved from 47/100 to
50/100, still the highest-ranked candidate, no ranking/decision changed.
This module's own field table below reflects the CORRECTED, accurate
reading.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class FieldProvenanceClassification(enum.Enum):
    """Part 1's exact 4-value vocabulary."""

    VENDOR_SUPPLIED = "vendor_supplied"
    RECONSTRUCTED = "reconstructed"
    DERIVED = "derived"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ORATSFieldMapping:
    normalized_field: str
    orats_source_field: str | None  # None when UNAVAILABLE -- no real field maps to it
    classification: FieldProvenanceClassification
    note: str


# Part 1's exact required field list, one row each.
ORATS_FIELD_PROVENANCE: tuple[ORATSFieldMapping, ...] = (
    ORATSFieldMapping("contract_identity", "Strike.ticker + Strike.strike + Strike.expiration_date + (call/put via field prefix)", FieldProvenanceClassification.VENDOR_SUPPLIED,
                        "A usable identity is real and confirmed; no separate single option-symbol/OCC-identifier field exists in the schema."),
    ORATSFieldMapping("underlying", "Strike.ticker", FieldProvenanceClassification.VENDOR_SUPPLIED, "Confirmed real field."),
    ORATSFieldMapping("option_type_call_put", "field-name prefix (call_*/put_*), not a distinct 'right' field", FieldProvenanceClassification.VENDOR_SUPPLIED,
                        "Confirmed real, but structurally different from a single explicit right/type column."),
    ORATSFieldMapping("strike", "Strike.strike", FieldProvenanceClassification.VENDOR_SUPPLIED, "Confirmed real field."),
    ORATSFieldMapping("expiration", "Strike.expiration_date", FieldProvenanceClassification.VENDOR_SUPPLIED, "Confirmed real field."),
    ORATSFieldMapping("multiplier", None, FieldProvenanceClassification.UNAVAILABLE, "No multiplier field observed anywhere in the fetched schema, any phase."),
    ORATSFieldMapping("timestamp", "Strike.trade_date (+ Strike.updated_at)", FieldProvenanceClassification.VENDOR_SUPPLIED, "Confirmed real fields; trade_date is also the confirmed historical query parameter."),
    ORATSFieldMapping("ohlc_underlying", "DailyPrice.open/high/low/close + unadjusted_open/high/low/close", FieldProvenanceClassification.VENDOR_SUPPLIED, "Confirmed real, both adjusted and unadjusted variants."),
    ORATSFieldMapping("bid", "Strike.call_bid_price / Strike.put_bid_price", FieldProvenanceClassification.VENDOR_SUPPLIED, "Confirmed real field."),
    ORATSFieldMapping("ask", "Strike.call_ask_price / Strike.put_ask_price", FieldProvenanceClassification.VENDOR_SUPPLIED, "Confirmed real field."),
    ORATSFieldMapping("bid_size", "Strike.call_bid_size / Strike.put_bid_size", FieldProvenanceClassification.VENDOR_SUPPLIED,
                        "Confirmed real field -- corrected this phase (Phase 28 originally, incorrectly, scored this UNAVAILABLE-tier; see module docstring)."),
    ORATSFieldMapping("ask_size", "Strike.call_ask_size / Strike.put_ask_size", FieldProvenanceClassification.VENDOR_SUPPLIED,
                        "Confirmed real field -- corrected this phase, same as bid_size."),
    ORATSFieldMapping("volume", "Strike.call_volume / Strike.put_volume", FieldProvenanceClassification.VENDOR_SUPPLIED, "Confirmed real field."),
    ORATSFieldMapping("open_interest", "Strike.call_open_interest / Strike.put_open_interest", FieldProvenanceClassification.VENDOR_SUPPLIED, "Confirmed real field."),
    ORATSFieldMapping("iv", "Strike.iv / Strike.external_iv (+ call_bid_iv/call_mid_iv/call_ask_iv per side)", FieldProvenanceClassification.VENDOR_SUPPLIED,
                        "Confirmed real field -- ORATS is the only provider evaluated any phase with a raw+bid/mid/ask IV schema this granular."),
    ORATSFieldMapping("delta", "Strike.delta", FieldProvenanceClassification.VENDOR_SUPPLIED, "Confirmed real field."),
    ORATSFieldMapping("gamma", "Strike.gamma", FieldProvenanceClassification.VENDOR_SUPPLIED, "Confirmed real field."),
    ORATSFieldMapping("theta", "Strike.theta", FieldProvenanceClassification.VENDOR_SUPPLIED, "Confirmed real field."),
    ORATSFieldMapping("vega", "Strike.vega", FieldProvenanceClassification.VENDOR_SUPPLIED, "Confirmed real field."),
    ORATSFieldMapping("rho", "Strike.rho", FieldProvenanceClassification.VENDOR_SUPPLIED, "Confirmed real field (also phi, driftless_theta -- beyond Part 1's explicit list, noted for completeness)."),
    ORATSFieldMapping("underlying_price", "Strike.underlying_price / Strike.spot_price", FieldProvenanceClassification.VENDOR_SUPPLIED, "Confirmed real field, TWO variants (spot_price vs underlying_price -- the exact distinction between them is not documented in evidence gathered any phase)."),
    # Beyond Part 1's literal list, but real and confirmed -- included for completeness of the adapter's real capability.
    ORATSFieldMapping("exercise_style", None, FieldProvenanceClassification.UNAVAILABLE, "No exercise-style field observed anywhere in the fetched schema, any phase."),
    ORATSFieldMapping("historical_volatility", "HistoricalVolatility.hv_1_day...hv_1000_day (11 windows) + ex-earnings variants", FieldProvenanceClassification.VENDOR_SUPPLIED, "Confirmed real, unusually granular."),
    ORATSFieldMapping("dividends", "DividendHistory.ex_dividend_date/dividend_amount/dividend_frequency/declared_date", FieldProvenanceClassification.VENDOR_SUPPLIED, "Confirmed real, dedicated endpoint."),
    ORATSFieldMapping("splits", "StockSplitHistory.split_date/divisor", FieldProvenanceClassification.VENDOR_SUPPLIED, "Confirmed real, dedicated endpoint -- see orats_corporate_actions.py for how this relates to the Phase 26 AAPL discontinuity."),
    ORATSFieldMapping("adjusted_contract_flag", None, FieldProvenanceClassification.UNAVAILABLE, "No explicit per-contract adjustment/adjusted-flag field observed anywhere in the fetched schema, any phase -- splits are a SEPARATE real endpoint (StockSplitHistory), never joined to a specific Strike row by any confirmed field."),
)


def rows_by_classification() -> dict[FieldProvenanceClassification, list[str]]:
    out: dict[FieldProvenanceClassification, list[str]] = {}
    for row in ORATS_FIELD_PROVENANCE:
        out.setdefault(row.classification, []).append(row.normalized_field)
    return out


def mapping_for(normalized_field: str) -> ORATSFieldMapping | None:
    return next((r for r in ORATS_FIELD_PROVENANCE if r.normalized_field == normalized_field), None)
