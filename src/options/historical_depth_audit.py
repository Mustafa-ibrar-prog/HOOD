"""Phase 24, Parts 2/6/7/18 — extends Phase 18's real
`OPTIONS_CAPABILITY_MATRIX` (src.options.capability_audit) with the
specific findings Phase 24's data-source audit needed and Phase 18
didn't test: how far back `get_option_instruments(state="expired")`
chain enumeration actually reaches, and an explicit reconciliation of
why that capability does NOT resolve point-in-time contract existence
(Part 7's exact distinction).

Every row below is backed by a real, read-only MCP probe made during
this phase (get_option_chains, get_option_instruments with
state="expired", get_option_quotes, get_option_historicals) -- not
inferred from tool names or Phase 18's prior findings. Phase 18's
matrix is imported and reused, not re-derived.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.options.capability_audit import OPTIONS_CAPABILITY_MATRIX, OptionsCapabilityRow, OptionsSourceCapability


@dataclass(frozen=True)
class HistoricalDepthProbe:
    underlying_symbol: str
    expiration_date_tested: str
    contracts_found: bool
    note: str


# Real probes, this phase: bracketing the earliest expiration `get_option_instruments(state="expired")`
# will actually enumerate contracts for. Robinhood's own options-trading launch (Dec 2017) is the
# expected real-world floor; these probes are consistent with that, not identical to Phase 18's separate
# AAPL anchor (2017-09-15) -- different underlyings can have different real listing histories, so these are
# additional data points, not a contradiction.
HISTORICAL_DEPTH_PROBES: tuple[HistoricalDepthProbe, ...] = (
    HistoricalDepthProbe("SPY", "2016-01-15", contracts_found=False, note="get_option_instruments(state='expired') returned zero contracts."),
    HistoricalDepthProbe("SPY", "2017-01-20", contracts_found=False, note="get_option_instruments(state='expired') returned zero contracts."),
    HistoricalDepthProbe("SPY", "2018-01-19", contracts_found=True, note="Returned a real, complete, paginated call-strike ladder ($40-$256+) -- full chain enumeration confirmed working at this date."),
    HistoricalDepthProbe("AAPL", "2019-01-18", contracts_found=True, note="Returned a real, complete, paginated call-strike ladder ($2.50-$265+); get_option_historicals for one of these contracts returned real daily OHLC back to 2018-11-01 with no fabricated/flat values."),
    HistoricalDepthProbe("AAPL", "2022-03-18", contracts_found=True, note="Returned the full 78-strike put ladder for this expiration ($70-$300) in one enumeration -- this is MORE strikes than Phase 19/20 actually gathered OHLC for (they hand-selected 3 strikes per underlying); a real, currently-unexploited data-expansion opportunity."),
)

# Part 7's exact distinction, made explicit: enumerating a contract via state="expired" proves the
# contract EXISTED AT SOME POINT (it reached expiration in Robinhood's own records) -- it does NOT prove
# the contract was listed/tradable on any EARLIER arbitrary date T, because no first_listed_date/
# first_trade_date/created_at field is present anywhere in the get_option_instruments response schema
# (confirmed by real probes above -- every returned object has exactly: id, chain_id, chain_symbol,
# underlying_type, expiration_date, sellout_datetime, strike_price, type, state, tradability,
# trade_value_multiplier, min_ticks -- no listing-date field of any kind). This is why
# src.options.contract_existence's ExistenceState.UNKNOWN_EXISTENCE classification for Phase 19/20's panel
# remains CORRECT even in light of chain enumeration working -- the two are answering different questions.
POINT_IN_TIME_EXISTENCE_RECONCILIATION = (
    "get_option_instruments(state='expired') answers 'did this contract EVER exist' (yes, verifiably, "
    "back to at least early-2018 for the underlyings probed) -- it does NOT answer 'was this contract "
    "listed and tradable on date T' for an arbitrary T before its expiration, because no first-listed-date "
    "field exists in the response schema. HISTORICAL_CONTRACT_EXISTENCE_UNKNOWN remains the correct "
    "classification for point-in-time existence; chain enumeration is a real, separate, and currently "
    "underused capability for EXPANDING historical OHLC coverage (Part 6/11), not for resolving PIT "
    "existence (Part 7)."
)


def historical_depth_lower_bound() -> str:
    """The earliest date this phase's real probes confirm state='expired' chain enumeration returns
    real contracts -- NOT a claim about the true floor (untested dates between the last-empty and
    first-populated probes above remain unknown)."""
    populated = [p for p in HISTORICAL_DEPTH_PROBES if p.contracts_found]
    return min(p.expiration_date_tested for p in populated) if populated else "unknown"


def extended_capability_matrix() -> tuple[OptionsCapabilityRow, ...]:
    """Phase 18's real matrix plus this phase's new row -- additive, Phase 18's tuple is never mutated."""
    new_row = OptionsCapabilityRow(
        data_field="Chain enumeration depth (state='expired')",
        capability=OptionsSourceCapability.HISTORICALLY_BACKFILLABLE,
        historical_depth=f"Confirmed real contracts back to at least {historical_depth_lower_bound()} "
                          f"(SPY/AAPL); empty for SPY at 2017-01-20 and 2016-01-15 -- consistent with "
                          f"Robinhood's own options-trading launch (Dec 2017).",
        evidence="Real get_option_instruments(state='expired') probes at 5 distinct expirations across 2 "
                  "underlyings, this phase -- see HISTORICAL_DEPTH_PROBES.",
        major_caveat=POINT_IN_TIME_EXISTENCE_RECONCILIATION,
    )
    return OPTIONS_CAPABILITY_MATRIX + (new_row,)
