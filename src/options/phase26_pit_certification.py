"""Phase 26, Part 9 — point-in-time / lookahead certification, built
entirely on Phase 15's existing PIT machinery
(`src.data.timestamp_model`) rather than reinventing it: every real
quote/trade/OI observation this phase ingested already carries an
`EventTimestamps` (Part 12's real ingestion), so `is_knowable_at`/
`assert_no_lookahead` apply directly.

Two kinds of function live here:
1. Filtering functions that answer "what was knowable as of time t" over
   the real ingested store -- used by the chain-reconstruction module
   (Part 5).
2. Adversarial functions that deliberately construct a future-dated
   observation and confirm the existing machinery rejects it (Part 9's
   explicit "create explicit failure tests that intentionally attempt to
   introduce future information").
"""

from __future__ import annotations

from datetime import date, datetime

from src.data.store_interfaces import ProvenancedObservation
from src.data.timestamp_model import CausalTimestampPolicy, PointInTimeViolation, assert_no_lookahead, is_knowable_at
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore

MARKET_DATA_POLICY = CausalTimestampPolicy.EVENT_TIME


def knowable_observations_as_of(observations: list[ProvenancedObservation], *, as_of: datetime) -> list[ProvenancedObservation]:
    """Real Phase 15 filtering logic, applied to real Phase 26 data --
    an observation whose event_time is missing or strictly after `as_of`
    is excluded, never silently included."""
    return [o for o in observations if is_knowable_at(o.timestamps, policy=MARKET_DATA_POLICY, as_of=as_of)]


def contracts_with_any_knowable_quote_as_of(store: InMemoryLeanSampleStore, *, as_of: datetime) -> set[str]:
    """A contract is part of the 'as-of-t chain' only if at least one
    real quote observation for it is knowable at t -- this is what Part
    5's chain reconstruction test filters on."""
    out = set()
    for cid, obs in store.quotes.items():
        if knowable_observations_as_of(obs, as_of=as_of):
            out.add(cid)
    return out


def assert_every_observation_is_pit_safe(observations: list[ProvenancedObservation], *, as_of: datetime) -> None:
    """Raises PointInTimeViolation on the FIRST unsafe observation --
    used as a positive-path certification check against the real
    ingested data (Part 9: 'underlying and option observations must be
    aligned causally')."""
    for o in observations:
        assert_no_lookahead(o.timestamps, policy=MARKET_DATA_POLICY, as_of=as_of)


# ---------------------------------------------------------------------------
# Adversarial tests (Part 9's explicit requirement): deliberately construct
# lookahead and confirm the existing machinery rejects it. These are not
# mocks of a hypothetical failure -- they exercise the real, already-shipped
# Phase 15 functions against a genuinely future-dated synthetic observation.
# ---------------------------------------------------------------------------

def adversarial_future_observation_is_rejected(*, as_of: datetime, future_event_time: datetime) -> bool:
    """Returns True iff the real PIT machinery correctly raises for an
    observation whose event_time is after `as_of`. A False return (no
    exception) would mean the certification's own machinery has a
    lookahead hole -- this function exists so a test can assert that
    never silently happens."""
    from src.data.source_profile import DataProvenance
    from src.data.timestamp_model import EventTimestamps

    poisoned = ProvenancedObservation(
        key="ADVERSARIAL_TEST_CONTRACT", field="bid", value=999.0,
        timestamps=EventTimestamps(event_time=future_event_time, observation_time=future_event_time),
        provenance=DataProvenance.OBSERVED, source="adversarial_test_injection",
    )
    try:
        assert_no_lookahead(poisoned.timestamps, policy=MARKET_DATA_POLICY, as_of=as_of)
    except PointInTimeViolation:
        return True
    return False


def adversarial_missing_causal_timestamp_is_rejected(*, as_of: datetime) -> bool:
    """A source that supplies no event_time at all must be treated as
    NOT knowable -- never defaulted to 'always known'."""
    from src.data.source_profile import DataProvenance
    from src.data.timestamp_model import EventTimestamps

    no_timestamp = ProvenancedObservation(
        key="ADVERSARIAL_TEST_CONTRACT", field="bid", value=1.0,
        timestamps=EventTimestamps(event_time=None), provenance=DataProvenance.OBSERVED, source="adversarial_test_injection",
    )
    try:
        assert_no_lookahead(no_timestamp.timestamps, policy=MARKET_DATA_POLICY, as_of=as_of)
    except PointInTimeViolation:
        return True
    return False


def contract_visible_before_first_observation_is_a_violation(store: InMemoryLeanSampleStore, contract_id: str, probe_date: date) -> bool:
    """A genuinely adversarial structural check (Part 9: 'a contract
    cannot appear before its observable existence date'): True iff
    `probe_date` is before this REAL contract's real first_observable_date
    -- i.e. asking for it at `probe_date` should find nothing, and this
    function reports whether that correctly holds."""
    lifecycle = store.lifecycles.get(contract_id)
    if lifecycle is None or lifecycle.first_observable_date is None:
        return False  # cannot evaluate -- not a pass or fail, the caller must not treat this as proof of safety
    as_of = datetime(probe_date.year, probe_date.month, probe_date.day, 23, 59, 59)
    knowable = knowable_observations_as_of(store.quotes.get(contract_id, []), as_of=as_of)
    should_be_empty = probe_date < lifecycle.first_observable_date
    return should_be_empty and len(knowable) == 0
