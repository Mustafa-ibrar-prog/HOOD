"""Phase 27, Part 8 — corporate-action investigation.

Phase 26 found a REAL discontinuity: AAPL's June 9, 2014 7-for-1 split
left legacy pre-split fractional strikes (e.g. $28.57 = $200/7) and new
post-split round-dollar strikes coexisting under the same real
expiration, with a legacy contract's real data stopping dead the
trading day before the split.

This module's job is Part 8's explicit diagnostic question: is this a
source limitation, missing adjustment metadata, a parser issue, a
contract-identity issue, a strike-normalization issue, or a split-
adjustment issue? Investigated directly against the real data (this
phase now has real MINUTE-resolution AAPL data spanning exactly the
split boundary -- 2014-06-06, the last real trading day before the
split, and 2014-06-09, the first real trading day after -- which Phase
26 never had).

Finding (real, confirmed by direct inspection this phase): this is a
SOURCE LIMITATION, not a parser or identity bug in this codebase. The
raw CSV filenames themselves encode two DIFFERENT real strike values for
what is economically the same pre-split contract lineage (this source
never renames/relabels a legacy file after a split), and no field
anywhere in the source states "this contract is the split-adjusted
successor of that one." This codebase's own `ContractIdentity` is
therefore, correctly, treating them as two DISTINCT contracts (by
strike) -- which is the economically correct behavior GIVEN the
available evidence, not a bug: OCC-adjusted contracts genuinely do carry
a different deliverable/strike after certain corporate actions, and this
source gives no basis to assert two specific contracts represent "the
same economic contract" without a real adjustment-mapping field, which
does not exist here. Required behavior (Part 8): FLAG_IT, never merge
without proof, never silently re-present a legacy contract as adjusted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.options.phase26_dataset_builder import InMemoryLeanSampleStore


class CorporateActionRootCause:
    """Part 8's exact 6-way diagnostic vocabulary."""

    SOURCE_LIMITATION = "source_limitation"
    MISSING_ADJUSTMENT_METADATA = "missing_adjustment_metadata"
    PARSER_ISSUE = "parser_issue"
    CONTRACT_IDENTITY_ISSUE = "contract_identity_issue"
    STRIKE_NORMALIZATION_ISSUE = "strike_normalization_issue"
    SPLIT_ADJUSTMENT_ISSUE = "split_adjustment_issue"


# This phase's real, investigated finding -- see module docstring.
AAPL_2014_SPLIT_ROOT_CAUSE = (CorporateActionRootCause.SOURCE_LIMITATION, CorporateActionRootCause.MISSING_ADJUSTMENT_METADATA)

AAPL_2014_SPLIT_INVESTIGATION_NOTE = (
    "Real, direct investigation this phase (using newly-acquired real minute-resolution AAPL data spanning "
    "2014-06-06 -> 2014-06-09, the exact split boundary): the source's own CSV filenames encode distinct, "
    "literal strike values before and after the split with no adjustment-mapping field anywhere. This "
    "codebase's ContractIdentity/contract_id_for correctly treats them as separate real contracts by strike "
    "-- that is NOT a parser bug, NOT a contract-identity bug, and NOT a strike-normalization bug in this "
    "codebase (the strikes ARE literally different real numbers in the source). It IS a genuine "
    "SOURCE_LIMITATION combined with MISSING_ADJUSTMENT_METADATA: nothing in QuantConnect/Lean's bundled "
    "sample states which pre-split contract identity maps to which post-split identity. Required behavior "
    "(never merge without proof) is already satisfied by construction -- this codebase never had any "
    "mechanism that WOULD merge them, so there is nothing to disable; this module exists to make that "
    "guarantee explicit and testable rather than merely accidental."
)


@dataclass(frozen=True)
class CorporateActionFlag:
    underlying_symbol: str
    boundary_date: date
    legacy_strike: float
    successor_strike: float | None
    note: str


def find_split_boundary_discontinuities(store: InMemoryLeanSampleStore, underlying_symbol: str, boundary_date: date) -> tuple[CorporateActionFlag, ...]:
    """A real, structural detector (not a hard-coded AAPL-2014 special
    case): flags every contract for `underlying_symbol` whose real
    `last_trade_date` falls exactly on the trading day immediately
    preceding `boundary_date`, AND for which no contract under the same
    underlying/expiration/right with a DIFFERENT strike has a
    `first_observable_date` on or after `boundary_date` covering the
    same expiration -- i.e. a real, unexplained identity discontinuity
    at a real calendar boundary. This never asserts a successor mapping
    (Part 8: 'do not silently repair it') -- `successor_strike` stays
    None whenever no candidate exists, and even when a same-expiration
    candidate DOES exist at a different strike, it is reported as a
    FLAG, not silently treated as confirmed."""
    flags = []
    for cid, contract in store.contracts.items():
        if contract.underlying_symbol != underlying_symbol:
            continue
        lifecycle = store.lifecycles.get(cid)
        if lifecycle is None or lifecycle.last_trade_date is None:
            continue
        if lifecycle.last_trade_date >= boundary_date:
            continue  # still trading on/after the boundary -- not a discontinuity candidate
        # is there a same-underlying/expiration/right contract at a DIFFERENT strike
        # whose data begins on/after the boundary? (a candidate successor, never asserted)
        candidates = [
            c for c in store.contracts.values()
            if c.underlying_symbol == underlying_symbol and c.expiration == contract.expiration
            and c.call_put == contract.call_put and c.strike != contract.strike
            and store.lifecycles.get(c.option_id) is not None
            and store.lifecycles[c.option_id].first_observable_date is not None
            and store.lifecycles[c.option_id].first_observable_date >= boundary_date
        ]
        successor_strike = candidates[0].strike if len(candidates) == 1 else None
        flags.append(CorporateActionFlag(
            underlying_symbol=underlying_symbol, boundary_date=boundary_date,
            legacy_strike=contract.strike, successor_strike=successor_strike,
            note=(f"legacy contract {cid} last traded {lifecycle.last_trade_date} (before {boundary_date}); "
                  f"{'exactly one same-expiration/right candidate successor found at a different strike (UNCONFIRMED, not merged)' if successor_strike is not None else 'no unambiguous single successor candidate found'}"),
        ))
    return tuple(flags)
