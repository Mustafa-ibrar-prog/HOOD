"""Phase 18, Part 6-8 — the real historical-options-data capability audit.

Every row below is backed by a real, read-only probe made during this
phase's development (mcp__HOOD__get_option_chains, get_option_instruments,
get_option_historicals, get_option_quotes) — not inferred from tool
names or documentation. Nothing here is guessed.

DECISIVE FINDINGS (see each row's evidence field for detail):
  - Contract IDENTITY for expired/historical contracts IS real and
    enumerable: get_option_instruments(chain_symbol=..., state="expired")
    returned real AAPL contracts spanning 2017-09-15 through 2026, both
    with and without an explicit expiration_dates filter.
  - Historical OHLC PRICE bars for a real, historical, expired contract
    ARE real: get_option_historicals on a real Jan-2022-expiry AAPL
    $175 call (instrument c55a630e-...) returned rich, volatile, clearly
    genuine daily price action from 2021-12-01 through 2022-01-20 (open
    3.90 -> close 0.01 as the contract decayed toward expiration) --
    squarely inside the 2021-2023 discovery window. A DEEP-OTM contract's
    historicals over the same window were flat at $0.01 every day with
    no `interpolated` flag either way -- plausible (a deep-OTM contract
    can genuinely pin near its tick floor) but NOT independently
    confirmed genuine the way the near-the-money contract was; flagged
    as a documented caveat, not asserted either way.
  - Historical option VOLUME is confirmed NEVER available, for any
    contract or date: the tool's own guide text states "Option bars
    carry no volume."
  - Historical bid/ask/open-interest/IV/Greeks are confirmed UNAVAILABLE:
    get_option_quotes (the only endpoint carrying any of these) returned
    an EMPTY result set for a real expired/untradable contract -- this
    endpoint is LIVE-ONLY, full stop.
  - The LIVE get_option_quotes payload is much richer than this codebase
    currently parses: a real probe (AAPL $230C 2026-09-18) returned
    bid/ask/bid_size/ask_size/mark/adjusted_mark/break_even_price/
    high_low_fill_rate prices/previous_close/IMPLIED_VOLATILITY/DELTA/
    GAMMA/THETA/VEGA/RHO/open_interest/volume/chance_of_profit_long/
    chance_of_profit_short/updated_at -- none of Greeks/IV/bid_size/
    ask_size/break_even/fill-rates/chance-of-profit are parsed into
    src.market.models.OptionQuote today (a real, documented, unclaimed
    extension point, same pattern Phase 14 found for equity bid/ask).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class OptionsSourceCapability(enum.Enum):
    """Part 6's exact classification vocabulary."""

    AVAILABLE_NOW = "available_now"
    AVAILABLE_WITH_EXISTING_TOOLING = "available_with_existing_tooling"
    HISTORICALLY_BACKFILLABLE = "historically_backfillable"
    PARTIALLY_BACKFILLABLE = "partially_backfillable"
    LIVE_ONLY = "live_only"
    INSUFFICIENT = "insufficient"
    UNAVAILABLE = "unavailable"
    PAID_REQUIRED = "paid_required"


@dataclass(frozen=True)
class OptionsCapabilityRow:
    data_field: str
    capability: OptionsSourceCapability
    historical_depth: str
    evidence: str
    major_caveat: str


OPTIONS_CAPABILITY_MATRIX: tuple[OptionsCapabilityRow, ...] = (
    OptionsCapabilityRow(
        data_field="Contract identity (strike/type/expiration/multiplier/min_ticks)",
        capability=OptionsSourceCapability.HISTORICALLY_BACKFILLABLE,
        historical_depth="Confirmed real contracts from 2017-09-15 through 2026 (AAPL); state='expired' enumerable with or without an expiration_dates filter.",
        evidence="Real get_option_instruments(chain_symbol='AAPL', state='expired') probe -- 105 contracts returned across many real historical expirations, paginated by strike.",
        major_caveat="Confirms contract EXISTENCE/metadata, not a first-listed timestamp -- see point_in_time.py: contract_existed_at() returns None (not True) for any as_of before expiration, since first-listed date is never supplied.",
    ),
    OptionsCapabilityRow(
        data_field="Historical option OHLC price bars (open/high/low/close)",
        capability=OptionsSourceCapability.HISTORICALLY_BACKFILLABLE,
        historical_depth="Confirmed real for a Dec-2021..Jan-2022 near-the-money AAPL $175C (expired 2022-01-21) -- squarely inside the 2021-2023 discovery window.",
        evidence="Real get_option_historicals(instrument_ids=['c55a630e-...'], start=2021-12-01, end=2022-01-21, interval='day') -- rich, volatile, economically plausible daily OHLC (open 3.90 decaying to close 0.01 near expiration), no repeated/flat values.",
        major_caveat="A DEEP-OTM contract over the same window showed a flat $0.01 series every day with no interpolated flag either way -- plausible (tick-floor pinning) but not independently confirmed genuine. Treat deep-OTM historical series with caution; near-the-money/liquid contracts are the safer case.",
    ),
    OptionsCapabilityRow(
        data_field="Historical option volume",
        capability=OptionsSourceCapability.UNAVAILABLE,
        historical_depth="Never available, any contract, any date.",
        evidence="get_option_historicals' own guide text states explicitly: 'Option bars carry no volume.'",
        major_caveat="Permanent limitation of this connector, not a coverage-depth question.",
    ),
    OptionsCapabilityRow(
        data_field="Historical bid/ask",
        capability=OptionsSourceCapability.UNAVAILABLE,
        historical_depth="Never available for an expired/historical contract.",
        evidence="Real get_option_quotes probe against a real expired contract returned results=[] (empty) -- confirmed live-only, not a fetch failure.",
        major_caveat="The only endpoint carrying bid/ask (get_option_quotes) is structurally a live snapshot tool -- no time-range parameter exists.",
    ),
    OptionsCapabilityRow(
        data_field="Historical open interest",
        capability=OptionsSourceCapability.UNAVAILABLE,
        historical_depth="Never available historically.",
        evidence="Only present in get_option_quotes (live-only, confirmed empty for an expired contract); absent from get_option_historicals' bar shape.",
        major_caveat="Same root cause as bid/ask -- no historical archive of quote-level data exists.",
    ),
    OptionsCapabilityRow(
        data_field="Historical implied volatility",
        capability=OptionsSourceCapability.UNAVAILABLE,
        historical_depth="Never available historically.",
        evidence="Confirmed present in a LIVE get_option_quotes response (implied_volatility=0.822619, real probe) but absent from get_option_historicals' bar shape.",
        major_caveat="Live IV IS available (see the 'Live options quote fields' row) but is not currently parsed into this codebase's OptionQuote model, and cannot be backdated regardless.",
    ),
    OptionsCapabilityRow(
        data_field="Historical Greeks (delta/gamma/theta/vega/rho)",
        capability=OptionsSourceCapability.UNAVAILABLE,
        historical_depth="Never available historically.",
        evidence="Confirmed present in a LIVE get_option_quotes response (delta=0.982989, gamma=0.000756, theta=-0.097964, vega=0.028455, rho=0.096388, real probe) but absent from get_option_historicals' bar shape.",
        major_caveat="Same as IV -- live-only, and not currently parsed into OptionQuote even for the live case.",
    ),
    OptionsCapabilityRow(
        data_field="Live options quote fields (bid/ask/size/mark/Greeks/IV/OI/volume/break-even/fill-rates/chance-of-profit)",
        capability=OptionsSourceCapability.AVAILABLE_WITH_EXISTING_TOOLING,
        historical_depth="Current instant only.",
        evidence="Real get_option_quotes probe (AAPL $230C 2026-09-18): full field list confirmed present in the raw response.",
        major_caveat="Rich live capability, but NOT currently parsed into src.market.models.OptionQuote (which only surfaces bid/ask/last/volume/open_interest) -- a real, documented, unclaimed extension point for a future live-trading-path change (out of scope for this research-layer phase).",
    ),
    OptionsCapabilityRow(
        data_field="Option chain structure (expirations/strikes currently listed)",
        capability=OptionsSourceCapability.AVAILABLE_WITH_EXISTING_TOOLING,
        historical_depth="Current/future listing only (get_option_chains showed expirations from today through ~2028).",
        evidence="Real get_option_chains(underlying_symbol='AAPL') probe.",
        major_caveat="Does not itself expose historical chain structure -- get_option_instruments(state='expired') is the real path to historical contract identity, not get_option_chains.",
    ),
)


def summarize_capability() -> dict[OptionsSourceCapability, list[str]]:
    out: dict[OptionsSourceCapability, list[str]] = {}
    for row in OPTIONS_CAPABILITY_MATRIX:
        out.setdefault(row.capability, []).append(row.data_field)
    return out
