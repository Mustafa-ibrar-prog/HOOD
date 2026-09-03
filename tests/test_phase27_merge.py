"""Phase 27, Part 7/16 — the merge layer: deterministic ordering
regardless of input order, exact-duplicate collapsing, and explicit
conflict recording (never silently choosing a value) using SYNTHETIC_
TEST_DATA fixtures, per Part 4's labeling rule -- never mixed with any
real dataset."""

from __future__ import annotations

from datetime import datetime

from src.data.source_profile import DataProvenance
from src.data.store_interfaces import ProvenancedObservation
from src.data.timestamp_model import EventTimestamps
from src.options.phase27_merge import merge_observation_lists, merged_quotes_by_contract

# SYNTHETIC_TEST_DATA -- never real, never persisted as part of the actual dataset.


def _obs(key, field, value, ts, source="synthetic_test_source"):
    return ProvenancedObservation(key=key, field=field, value=value,
                                   timestamps=EventTimestamps(event_time=ts, observation_time=ts),
                                   provenance=DataProvenance.OBSERVED, source=source)


def test_merge_is_deterministic_regardless_of_input_order():
    cid = "SYNTH_call_100.0000_2020-01-17"
    a = [_obs(cid, "bid", 1.0, datetime(2020, 1, 2))]
    b = [_obs(cid, "bid", 2.0, datetime(2020, 1, 3))]
    merged1, _ = merge_observation_lists(a, b)
    merged2, _ = merge_observation_lists(b, a)
    assert [(o.value, o.timestamps.event_time) for o in merged1] == [(o.value, o.timestamps.event_time) for o in merged2]


def test_merge_sorts_by_event_time_regardless_of_source_directory_order():
    """This is exactly the real bug this phase found and fixed: daily
    rows for a later date must not precede minute rows for an earlier
    date in the merged output."""
    cid = "SYNTH_call_100.0000_2020-01-17"
    daily_late = [_obs(cid, "bid", 9.0, datetime(2020, 1, 31, 0, 0))]
    minute_early = [_obs(cid, "bid", 1.0, datetime(2020, 1, 2, 9, 30))]
    merged, _ = merge_observation_lists(daily_late, minute_early)
    timestamps = [o.timestamps.event_time for o in merged]
    assert timestamps == sorted(timestamps)


def test_exact_duplicate_observations_collapse_to_one():
    cid = "SYNTH_call_100.0000_2020-01-17"
    ts = datetime(2020, 1, 2)
    a = [_obs(cid, "bid", 1.0, ts)]
    b = [_obs(cid, "bid", 1.0, ts)]  # identical in every field
    merged, conflicts = merge_observation_lists(a, b)
    assert len(merged) == 1
    assert conflicts == []


def test_differing_values_at_the_same_key_field_timestamp_are_recorded_as_a_conflict_never_silently_resolved():
    cid = "SYNTH_call_100.0000_2020-01-17"
    ts = datetime(2020, 1, 2)
    a = [_obs(cid, "bid", 1.0, ts, source="synthetic_source_a")]
    b = [_obs(cid, "bid", 2.0, ts, source="synthetic_source_b")]
    merged, conflicts = merge_observation_lists(a, b)
    # BOTH values must survive in the merged output -- never silently picking one
    assert {o.value for o in merged} == {1.0, 2.0}
    assert len(conflicts) == 1
    c = conflicts[0]
    assert set(c.values) == {1.0, 2.0}
    assert set(c.sources) == {"synthetic_source_a", "synthetic_source_b"}


def test_merge_never_drops_a_genuine_disagreement_even_with_three_sources():
    cid = "SYNTH_call_100.0000_2020-01-17"
    ts = datetime(2020, 1, 2)
    a = [_obs(cid, "bid", 1.0, ts, source="src_a")]
    b = [_obs(cid, "bid", 1.0, ts, source="src_b")]  # agrees with a
    c = [_obs(cid, "bid", 5.0, ts, source="src_c")]  # disagrees
    merged, conflicts = merge_observation_lists(a, b, c)
    assert {o.value for o in merged} == {1.0, 5.0}
    assert len(conflicts) == 1


def test_merged_quotes_by_contract_handles_multiple_contracts_independently():
    cid1, cid2 = "SYNTH_call_100.0000_2020-01-17", "SYNTH_put_100.0000_2020-01-17"
    d1 = {cid1: [_obs(cid1, "bid", 1.0, datetime(2020, 1, 2))]}
    d2 = {cid2: [_obs(cid2, "bid", 2.0, datetime(2020, 1, 2))]}
    merged, conflicts = merged_quotes_by_contract(d1, d2)
    assert set(merged.keys()) == {cid1, cid2}
    assert conflicts == []


def test_merged_quotes_by_contract_is_a_no_op_for_a_single_source():
    cid = "SYNTH_call_100.0000_2020-01-17"
    d1 = {cid: [_obs(cid, "bid", 1.0, datetime(2020, 1, 2)), _obs(cid, "bid", 2.0, datetime(2020, 1, 3))]}
    merged, conflicts = merged_quotes_by_contract(d1)
    assert [o.value for o in merged[cid]] == [1.0, 2.0]
    assert conflicts == []
