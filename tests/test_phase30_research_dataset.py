"""Phase 30, Part 1/17 — the research dataset abstraction layer."""

from __future__ import annotations

from datetime import date

from src.options.research_dataset import (
    DataQualityStatus,
    PITStatus,
    build_research_observations,
    observations_for_contract,
    observations_for_underlying,
)
from tests.phase30_fixtures import synthetic_store, synthetic_store_with_crossed_market


def test_builds_one_row_per_real_timestamp():
    store = synthetic_store()
    rows = build_research_observations(store)
    assert len(rows) == 2  # ts0 and ts1


def test_every_row_carries_all_required_fields():
    store = synthetic_store()
    rows = build_research_observations(store)
    for r in rows:
        assert r.underlying == "AAPL"
        assert r.call_put == "call"
        assert r.strike == 100.0
        assert r.expiration == date(2026, 12, 18)
        assert r.data_source == "quantconnect_lean_open_source_sample"
        assert r.provenance is not None


def test_moneyness_and_dte_computed_from_real_aligned_data():
    store = synthetic_store()
    rows = build_research_observations(store)
    row = rows[0]
    assert row.underlying_price == 190.0
    assert row.moneyness == 100.0 / 190.0
    assert row.dte == (date(2026, 12, 18) - date(2026, 8, 1)).days


def test_row_missing_underlying_price_has_none_moneyness_not_fabricated():
    from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
    store = synthetic_store()
    # Blank out the underlying price entirely.
    stripped = InMemoryLeanSampleStore(
        contracts=store.contracts, lifecycles=store.lifecycles, quotes=store.quotes,
        trades=store.trades, open_interest=store.open_interest, underlying={},
    )
    rows = build_research_observations(stripped)
    assert all(r.underlying_price is None and r.moneyness is None for r in rows)


def test_second_timestamp_has_no_trade_or_oi_never_fabricated():
    store = synthetic_store()
    rows = build_research_observations(store)
    ts1_row = [r for r in rows if r.bid == 4.90][0]
    assert ts1_row.option_close is None
    assert ts1_row.open_interest is None
    assert ts1_row.bid == 4.90 and ts1_row.ask == 5.10


def test_clean_contract_has_only_the_permanent_multiplier_flag():
    store = synthetic_store()
    rows = build_research_observations(store)
    assert all(r.quality_flags == ("multiplier_not_source_confirmed",) for r in rows)
    assert all(r.data_quality == DataQualityStatus.FLAGGED_WARNING for r in rows)


def test_crossed_market_contract_flagged_critical():
    store = synthetic_store_with_crossed_market()
    rows = build_research_observations(store)
    assert len(rows) == 1
    assert rows[0].data_quality == DataQualityStatus.FLAGGED_CRITICAL
    assert "bid_gt_ask" in rows[0].quality_flags


def test_pit_status_always_safe_for_a_built_row():
    """Rows are only ever built from real event-time-bearing observations
    (None-timestamped observations are skipped, never given a fabricated
    timestamp) -- so every row that exists is PIT_SAFE by construction."""
    store = synthetic_store()
    rows = build_research_observations(store)
    assert all(r.pit_status == PITStatus.PIT_SAFE for r in rows)


def test_filters_by_contract_and_underlying():
    store = synthetic_store()
    rows = build_research_observations(store)
    cid = rows[0].option_id
    assert len(observations_for_contract(rows, cid)) == 2
    assert len(observations_for_contract(rows, "nonexistent")) == 0
    assert len(observations_for_underlying(rows, "AAPL")) == 2
    assert len(observations_for_underlying(rows, "MSFT")) == 0


def test_deterministic_ordering():
    store = synthetic_store()
    rows = build_research_observations(store)
    timestamps = [r.observation_timestamp for r in rows]
    assert timestamps == sorted(timestamps)


def test_empty_store_yields_no_rows():
    from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
    empty = InMemoryLeanSampleStore(contracts={}, lifecycles={}, quotes={}, trades={}, open_interest={}, underlying={})
    assert build_research_observations(empty) == []
