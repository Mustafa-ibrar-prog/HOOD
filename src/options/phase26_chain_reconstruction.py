"""Phase 26, Part 5 — historical chain reconstruction test, run against
the real ingested Lean sample. Reuses Part 9's PIT filtering
(`contracts_with_any_knowable_quote_as_of`) rather than re-deriving a
second notion of "as of."
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.options.historical_data_interfaces import ContractIdentity
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.phase26_pit_certification import contracts_with_any_knowable_quote_as_of


@dataclass(frozen=True)
class ChainReconstructionResult:
    as_of: datetime
    underlying_symbol: str
    reconstructed_contracts: tuple[ContractIdentity, ...]
    excluded_not_yet_observed: tuple[str, ...]  # real contract_ids whose first_observable_date is after as_of -- correctly excluded
    excluded_already_expired: tuple[str, ...]  # real contract_ids whose expiration is before as_of -- correctly excluded from a "live chain" view
    included_expired_but_within_lifetime: tuple[str, ...]  # contracts whose expiration is AFTER as_of, correctly included


def reconstruct_chain_as_of(store: InMemoryLeanSampleStore, underlying_symbol: str, as_of: datetime) -> ChainReconstructionResult:
    """The REAL reconstruction this data source actually supports: 'which
    contracts have at least one real, knowable-at-`as_of` quote
    observation.' This is a genuinely stronger test than pure eventual-
    existence (Phase 24/25's Robinhood finding) because every included
    contract has an ACTUAL observed row at or before `as_of`, not merely
    a state flag -- but it is still not a true vendor-asserted 'these
    were the tradable strikes' snapshot (this flat-file sample has no
    listing/delisting feed independent of when a row happens to exist)."""
    probe_date = as_of.date()
    knowable_ids = contracts_with_any_knowable_quote_as_of(store, as_of=as_of)

    not_yet_observed = []
    already_expired = []
    included = []
    for cid, contract in store.contracts.items():
        if contract.underlying_symbol != underlying_symbol:
            continue
        lifecycle = store.lifecycles.get(cid)
        if lifecycle is None or lifecycle.first_observable_date is None:
            continue
        if lifecycle.first_observable_date > probe_date:
            not_yet_observed.append(cid)
            continue
        if contract.expiration < probe_date:
            already_expired.append(cid)
            continue
        if cid in knowable_ids:
            included.append(cid)

    return ChainReconstructionResult(
        as_of=as_of,
        underlying_symbol=underlying_symbol,
        reconstructed_contracts=tuple(store.contracts[cid] for cid in included),
        excluded_not_yet_observed=tuple(not_yet_observed),
        excluded_already_expired=tuple(already_expired),
        included_expired_but_within_lifetime=tuple(included),
    )


def contracts_incorrectly_visible_before_first_observation(store: InMemoryLeanSampleStore, underlying_symbol: str, as_of: datetime) -> tuple[str, ...]:
    """A genuine adversarial check (Part 5, question 1: 'were contracts
    that had not yet existed excluded?') -- returns any contract_id that
    WOULD be wrongly included by a naive 'ignore lifecycle' reconstruction
    but is correctly excluded by `reconstruct_chain_as_of`. An empty tuple
    is the PASS case."""
    result = reconstruct_chain_as_of(store, underlying_symbol, as_of)
    violations = []
    for cid, contract in store.contracts.items():
        if contract.underlying_symbol != underlying_symbol:
            continue
        lifecycle = store.lifecycles.get(cid)
        if lifecycle and lifecycle.first_observable_date and lifecycle.first_observable_date > as_of.date():
            if any(c.option_id == cid for c in result.reconstructed_contracts):
                violations.append(cid)
    return tuple(violations)
