"""Phase 18, Part 5 — point-in-time correctness for options.

Options PIT is stricter than daily equities: a contract's mere existence
at time T cannot be assumed just because it exists today or exists in a
list of "expired" contracts we happened to fetch. Confirmed real
capability: get_option_instruments(state="expired") DOES let us query
what contracts existed (strike/type/expiration/multiplier), including
far in the past (real probe: AAPL contracts back to 2017-09-15) -- but
this only tells us a contract EXISTED AT SOME POINT, not that it was
LISTED AND TRADABLE at every timestamp between its first listing and its
expiration. This module is explicit about that gap: `contract_existed_at`
returns None (never a guessed True/False) whenever the evidence needed to
answer precisely -- a real "first listed" timestamp -- is not available,
which is the case for every contract this phase has access to (the
source does not expose a listing/first-traded date, only expiration and
state).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.options.instrument import OptionContract


@dataclass(frozen=True)
class ContractExistenceEvidence:
    """What we actually know about a contract's real-world listing
    window. `first_listed_date` is None for every contract this source
    has ever returned to this codebase -- documented explicitly rather
    than assumed to be "always listed since forever." `last_confirmed_
    active_date`/`expiration` bound the window from the other end."""

    contract: OptionContract
    first_listed_date: date | None  # NEVER populated by this phase's real data -- the source doesn't expose it
    expiration: date
    source: str


def contract_existed_at(evidence: ContractExistenceEvidence, *, as_of: datetime) -> bool | None:
    """Part 5: 'A contract that exists today must NOT automatically be
    assumed to have existed historically.' Returns:
      - False if as_of is after expiration (definitely did not exist --
        the contract had already stopped trading).
      - None if as_of is before expiration but first_listed_date is
        unknown (the honest answer given real data: we cannot rule out
        that the contract wasn't listed yet at that timestamp).
      - True only if first_listed_date is known and as_of falls within
        [first_listed_date, expiration] -- a case this phase's real data
        never actually produces, since first_listed_date is never known,
        but the logic is here for a future source that does supply it.
    """
    if as_of.date() > evidence.expiration:
        return False
    if evidence.first_listed_date is None:
        return None
    if as_of.date() < evidence.first_listed_date:
        return False
    return True


def assert_no_survivorship_bias_in_contract_universe(contracts: list[OptionContract], *, as_of: date) -> list[str]:
    """A static guard, not a data-quality check on individual contracts:
    returns a list of warnings for any contract in `contracts` whose
    expiration is AFTER `as_of` by more than a schedule-implied amount
    that would suggest it was selected using knowledge only available
    later (e.g. a strike chosen because the underlying moved there,
    which wasn't knowable at `as_of`). This phase does not implement a
    strike-selection-bias detector (that requires knowing WHY a strike
    was chosen, which is a strategy-level concern, not a data-fact) --
    it only flags the structural case: a contract whose OWN expiration
    predates `as_of` cannot possibly have been used correctly."""
    warnings: list[str] = []
    for contract in contracts:
        if contract.expiration < as_of:
            warnings.append(
                f"{contract.option_id} ({contract.occ_style_description}) expired {contract.expiration} "
                f"before as_of={as_of} -- cannot be a valid contract choice at this as_of"
            )
    return warnings
