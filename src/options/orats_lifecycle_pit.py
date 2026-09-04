"""Phase 29, Part 4/7 — ORATS contract lifecycle and PIT (point-in-time)
certification. Reuses Phase 15/26's existing PIT machinery and Phase
26's chain-reconstruction function unchanged (both operate structurally
on the shared `InMemoryLeanSampleStore` shape) -- nothing new to build
for the mechanism itself; this module adds the ORATS-specific PIT_
CONTRACT_EXISTENCE_LIMITED classification Part 7 requires.
"""

from __future__ import annotations

from datetime import datetime

from src.options.phase26_chain_reconstruction import contracts_incorrectly_visible_before_first_observation, reconstruct_chain_as_of
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.phase26_pit_certification import (
    adversarial_future_observation_is_rejected,
    adversarial_missing_causal_timestamp_is_rejected,
    contracts_with_any_knowable_quote_as_of,
    knowable_observations_as_of,
)

# Re-exported for a single, ORATS-scoped import point in tests/reports --
# these are the exact same real, already-tested Phase 15/26 functions.
__all__ = [
    "adversarial_future_observation_is_rejected",
    "adversarial_missing_causal_timestamp_is_rejected",
    "contracts_with_any_knowable_quote_as_of",
    "knowable_observations_as_of",
    "reconstruct_chain_as_of",
    "contracts_incorrectly_visible_before_first_observation",
    "PIT_CONTRACT_EXISTENCE_LIMITED",
    "orats_pit_status",
]

# Part 7's exact required label, applied honestly: ORATS's real schema
# (Phase 25's evidence, re-confirmed this phase, no new probe) has NO
# first-listed-date/first-observed-date field anywhere -- Ticker.min_date/
# max_date describe DATA COVERAGE range for a symbol, not a per-contract
# listing date (the same distinction Phase 24/26/27 drew for Robinhood
# and QuantConnect/Lean). The confirmed real `trade_date` query parameter
# is a genuine, stronger-than-eventual-existence PIT mechanism (it lets a
# caller ask "what did the chain look like as of trade_date T" directly)
# -- but it still does not answer "was THIS contract listed before T,"
# only "does a row exist for T." Both facts must be held at once, honestly.
PIT_CONTRACT_EXISTENCE_LIMITED = (
    "ORATS's real schema has no first-listed-date/first-observed-date field for any contract -- "
    "PIT_CONTRACT_EXISTENCE_LIMITED applies, identically to every other provider evaluated this project "
    "(Robinhood, QuantConnect/Lean). The real trade_date query parameter is a genuinely stronger PRACTICAL "
    "PIT mechanism than Robinhood's eventual-existence-only capability (it directly answers 'what did the "
    "chain look like as of date T'), but it does not resolve the first-listed-date gap -- these are two "
    "different questions, and conflating them would misrepresent what trade_date actually proves."
)


def orats_pit_status(store: InMemoryLeanSampleStore, underlying_symbol: str, as_of: datetime) -> dict:
    """A single real, reusable summary combining the reused Phase 26
    chain-reconstruction result with the honest PIT_CONTRACT_EXISTENCE_
    LIMITED classification -- built on real (or, before real ORATS
    access, real free-dataset-shaped test) data, never fabricated."""
    result = reconstruct_chain_as_of(store, underlying_symbol, as_of)
    violations = contracts_incorrectly_visible_before_first_observation(store, underlying_symbol, as_of)
    return {
        "as_of": as_of.isoformat(),
        "reconstructed_contract_count": len(result.reconstructed_contracts),
        "excluded_not_yet_observed_count": len(result.excluded_not_yet_observed),
        "excluded_already_expired_count": len(result.excluded_already_expired),
        "adversarial_violations": len(violations),
        "pit_contract_existence_limited": PIT_CONTRACT_EXISTENCE_LIMITED,
    }
