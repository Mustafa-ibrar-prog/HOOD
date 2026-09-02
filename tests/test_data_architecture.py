"""Phase 15, Part 19 — tests for the genuinely NEW architecture only
(timestamp model, generic quality checks, dataset versioning, store
interfaces, source-profile matrix invariants). Per Part 19's explicit
instruction, no tests are added for functionality that does not yet
exist (there is no concrete FundamentalStore/EarningsStore/OptionsStore/
MacroStore implementation this phase — only the Protocols/record shape)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.generic_quality import (
    find_duplicate_timestamps,
    find_out_of_order_indices,
    find_publication_time_violations,
    find_timezone_naive_indices,
)
from src.data.source_profile import DATA_SOURCE_MATRIX, AvailabilityClass, DataProvenance, ResearchSuitability
from src.data.store import HistoricalDataStore
from src.data.store_interfaces import (
    EarningsStore,
    FundamentalStore,
    HistoricalBarStore,
    MacroStore,
    OptionsStore,
    ProvenancedObservation,
    QuoteStore,
    TradeStore,
)
from src.data.timestamp_model import CausalTimestampPolicy, EventTimestamps, PointInTimeViolation, assert_no_lookahead, is_knowable_at
from src.data.universe import us_diversified_universe
from src.data.versioning import DatasetVersionRecord, compute_universe_version


# --- timestamp model ---------------------------------------------------------------------------


def test_causal_timestamp_selects_the_right_field_per_policy():
    ts = EventTimestamps(
        event_time=datetime(2021, 9, 25, tzinfo=timezone.utc),
        observation_time=datetime(2021, 9, 26, tzinfo=timezone.utc),
        publication_time=datetime(2021, 10, 29, tzinfo=timezone.utc),
    )
    assert ts.causal_timestamp(CausalTimestampPolicy.EVENT_TIME) == ts.event_time
    assert ts.causal_timestamp(CausalTimestampPolicy.OBSERVATION_TIME) == ts.observation_time
    assert ts.causal_timestamp(CausalTimestampPolicy.PUBLICATION_TIME) == ts.publication_time


def test_missing_causal_field_is_not_knowable_ever():
    ts = EventTimestamps(event_time=datetime(2021, 9, 25, tzinfo=timezone.utc))  # no publication_time
    far_future = datetime(2030, 1, 1, tzinfo=timezone.utc)
    assert is_knowable_at(ts, policy=CausalTimestampPolicy.PUBLICATION_TIME, as_of=far_future) is False


def test_assert_no_lookahead_raises_on_missing_publication_time():
    """This is Part 19's 'safety against future publication dates' test,
    applied to the exact failure mode Phase 15's own audit found real:
    get_financials never supplies a filing/publication date."""
    ts = EventTimestamps(event_time=datetime(2021, 9, 25, tzinfo=timezone.utc))
    with pytest.raises(PointInTimeViolation):
        assert_no_lookahead(ts, policy=CausalTimestampPolicy.PUBLICATION_TIME, as_of=datetime(2030, 1, 1, tzinfo=timezone.utc))


def test_assert_no_lookahead_raises_when_publication_time_is_in_the_future_of_as_of():
    ts = EventTimestamps(publication_time=datetime(2021, 10, 29, tzinfo=timezone.utc))
    with pytest.raises(PointInTimeViolation):
        assert_no_lookahead(ts, policy=CausalTimestampPolicy.PUBLICATION_TIME, as_of=datetime(2021, 10, 1, tzinfo=timezone.utc))


def test_assert_no_lookahead_passes_once_as_of_reaches_publication_time():
    ts = EventTimestamps(publication_time=datetime(2021, 10, 29, tzinfo=timezone.utc))
    assert_no_lookahead(ts, policy=CausalTimestampPolicy.PUBLICATION_TIME, as_of=datetime(2021, 10, 29, tzinfo=timezone.utc))  # exact instant: not a violation
    assert_no_lookahead(ts, policy=CausalTimestampPolicy.PUBLICATION_TIME, as_of=datetime(2021, 11, 1, tzinfo=timezone.utc))


# --- generic quality checks ---------------------------------------------------------------------


def test_find_duplicate_timestamps():
    t0 = datetime(2022, 1, 3, tzinfo=timezone.utc)
    series = [t0, t0 + timedelta(days=1), t0 + timedelta(days=1), t0 + timedelta(days=3)]
    assert find_duplicate_timestamps(series) == {t0 + timedelta(days=1): 2}
    assert find_duplicate_timestamps([t0, t0 + timedelta(days=1)]) == {}


def test_find_out_of_order_indices():
    t0 = datetime(2022, 1, 3, tzinfo=timezone.utc)
    series = [t0, t0 - timedelta(days=1), t0 + timedelta(days=2)]
    assert find_out_of_order_indices(series) == [1]
    assert find_out_of_order_indices([t0, t0 + timedelta(days=1), t0 + timedelta(days=2)]) == []


def test_find_timezone_naive_indices():
    naive = datetime(2022, 1, 3)
    aware = datetime(2022, 1, 3, tzinfo=timezone.utc)
    assert find_timezone_naive_indices([aware, naive, aware]) == [1]
    assert find_timezone_naive_indices([aware, aware]) == []


def test_find_publication_time_violations():
    as_of = datetime(2021, 10, 1, tzinfo=timezone.utc)
    unsafe = EventTimestamps(event_time=datetime(2021, 9, 25, tzinfo=timezone.utc))  # no publication_time
    not_yet_public = EventTimestamps(publication_time=datetime(2021, 10, 29, tzinfo=timezone.utc))
    already_public = EventTimestamps(publication_time=datetime(2021, 9, 1, tzinfo=timezone.utc))
    result = find_publication_time_violations(
        [unsafe, not_yet_public, already_public], policy=CausalTimestampPolicy.PUBLICATION_TIME, as_of=as_of
    )
    assert result == [0, 1]


# --- dataset versioning --------------------------------------------------------------------------


def test_compute_universe_version_is_order_independent_and_deterministic():
    universe = us_diversified_universe()
    v1 = compute_universe_version(universe)
    v2 = compute_universe_version(universe)
    assert v1 == v2
    assert isinstance(v1, str) and len(v1) == 16


def test_dataset_version_record_fingerprint_is_deterministic_and_sensitive_to_changes():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    base = DatasetVersionRecord(
        source="test", retrieval_timestamp=now, source_version="v1", schema_version="s1",
        adjustment_status="none", universe_version="uv1",
    )
    same = DatasetVersionRecord(
        source="test", retrieval_timestamp=now, source_version="v1", schema_version="s1",
        adjustment_status="none", universe_version="uv1",
    )
    changed = DatasetVersionRecord(
        source="test", retrieval_timestamp=now, source_version="v2", schema_version="s1",
        adjustment_status="none", universe_version="uv1",
    )
    assert base.fingerprint() == same.fingerprint()
    assert base.fingerprint() != changed.fingerprint()


# --- store interfaces -----------------------------------------------------------------------------


def test_historical_data_store_structurally_satisfies_historical_bar_store_protocol(tmp_path):
    store = HistoricalDataStore(tmp_path)
    assert isinstance(store, HistoricalBarStore)


def test_new_store_protocols_are_satisfied_by_a_minimal_conforming_fake():
    class _FakeStore:
        def load(self, key: str) -> list[ProvenancedObservation]:
            return []

        def save(self, key: str, observations, *, source: str = "test") -> object:
            return None

    fake = _FakeStore()
    assert isinstance(fake, QuoteStore)
    assert isinstance(fake, TradeStore)
    assert isinstance(fake, FundamentalStore)
    assert isinstance(fake, EarningsStore)
    assert isinstance(fake, OptionsStore)
    assert isinstance(fake, MacroStore)


def test_provenanced_observation_carries_a_causal_timestamp():
    ts = EventTimestamps(publication_time=datetime(2021, 10, 29, tzinfo=timezone.utc))
    obs = ProvenancedObservation(key="AAPL", field="revenue", value=1.0, timestamps=ts, provenance=DataProvenance.OBSERVED, source="test")
    assert obs.timestamps.causal_timestamp(CausalTimestampPolicy.PUBLICATION_TIME) == ts.publication_time


# --- source-profile matrix invariants --------------------------------------------------------------


def test_data_source_matrix_is_nonempty_and_well_formed():
    assert len(DATA_SOURCE_MATRIX) >= 5
    for row in DATA_SOURCE_MATRIX:
        assert row.data_source and row.field
        assert row.major_caveat, f"{row.data_source} has no major_caveat documented"


def test_no_live_only_source_is_marked_historically_backfillable():
    """A source cannot be BOTH live-only AND claim it can backfill the
    past discovery window — that's exactly the confusion Part 3
    forbids ('never treat B or E as equivalent to D')."""
    for row in DATA_SOURCE_MATRIX:
        if row.availability == AvailabilityClass.LIVE_ONLY:
            assert row.research_suitability != ResearchSuitability.HIGH, (
                f"{row.data_source} is LIVE_ONLY but rated HIGH suitability — "
                "a live-only source cannot be highly suitable for backtesting research"
            )


def test_available_now_baseline_rows_are_rated_high_suitability():
    """The current, already-ingested baseline (Part 2) should never be
    rated below HIGH by this audit — it's the one source every prior
    phase has already relied on successfully."""
    baseline_rows = [row for row in DATA_SOURCE_MATRIX if row.availability == AvailabilityClass.AVAILABLE_NOW]
    assert baseline_rows, "expected at least one AVAILABLE_NOW row (the current daily OHLCV baseline)"
    for row in baseline_rows:
        assert row.research_suitability == ResearchSuitability.HIGH
