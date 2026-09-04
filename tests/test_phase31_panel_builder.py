"""Phase 31 — the panel-row adapter over the real free dataset store."""

from __future__ import annotations

from datetime import date

from src.options.phase31_panel_builder import (
    build_panel_rows,
    build_underlying_series,
    select_contracts,
    select_contracts_by_daily_richness,
    subset_store,
    underlying_forward_returns_at,
    underlyings_with_daily_coverage,
    underlying_trailing_return,
)
from tests.phase30_fixtures import synthetic_daily_multi_bar_store, synthetic_multi_bar_store, synthetic_store


def test_select_contracts_returns_all_when_under_the_cap():
    store = synthetic_daily_multi_bar_store(n_bars=5)
    ids = select_contracts(store, max_per_underlying=100)
    assert set(ids) == set(store.contracts.keys())


def test_select_contracts_strides_when_over_the_cap():
    # Build a store with several distinct contracts by combining two fixtures.
    a = synthetic_daily_multi_bar_store(n_bars=3, strike=100.0)
    b = synthetic_daily_multi_bar_store(n_bars=3, strike=105.0)
    from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
    combined = InMemoryLeanSampleStore(
        contracts={**a.contracts, **b.contracts}, lifecycles={**a.lifecycles, **b.lifecycles},
        quotes={**a.quotes, **b.quotes}, trades={**a.trades, **b.trades},
        open_interest={**a.open_interest, **b.open_interest}, underlying=a.underlying,
    )
    ids = select_contracts(combined, max_per_underlying=1)
    assert len(ids) == 1


def test_select_contracts_by_daily_richness_prefers_the_longer_real_history():
    richer = synthetic_daily_multi_bar_store(n_bars=10, strike=100.0)
    sparser = synthetic_daily_multi_bar_store(n_bars=2, strike=105.0)
    from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
    combined = InMemoryLeanSampleStore(
        contracts={**richer.contracts, **sparser.contracts}, lifecycles={**richer.lifecycles, **sparser.lifecycles},
        quotes={**richer.quotes, **sparser.quotes}, trades={**richer.trades, **sparser.trades},
        open_interest={**richer.open_interest, **sparser.open_interest}, underlying=richer.underlying,
    )
    richer_id = next(iter(richer.contracts))
    sparser_id = next(iter(sparser.contracts))
    ids = select_contracts_by_daily_richness(combined, max_per_underlying=1)
    assert ids == [richer_id]
    assert sparser_id not in ids


def test_select_contracts_by_daily_richness_excludes_intraday_only_contracts():
    from datetime import datetime, timezone
    from src.data.source_profile import DataProvenance
    from src.data.store_interfaces import ProvenancedObservation
    from src.data.timestamp_model import EventTimestamps
    from src.options.phase26_dataset_builder import (
        InMemoryLeanSampleStore, build_contract_identity, build_provenance,
    )
    from src.options.phase26_lean_sample_parser import LeanContractFileMeta

    daily = synthetic_daily_multi_bar_store(n_bars=5, strike=100.0)
    daily_id = next(iter(daily.contracts))

    provenance = build_provenance(retrieval_timestamp=datetime(2026, 9, 4, tzinfo=timezone.utc), adjustment_status="x")
    meta = LeanContractFileMeta("AAPL", "call", 110.0, date(2026, 12, 18), "quote", "american", None)
    intraday_contract = build_contract_identity(meta, provenance)
    intraday_id = intraday_contract.option_id
    ts = datetime(2026, 8, 1, 14, 30, tzinfo=timezone.utc)
    intraday_quotes = {intraday_id: [
        ProvenancedObservation(key=intraday_id, field="bid", value=1.0, timestamps=EventTimestamps(event_time=ts), provenance=DataProvenance.OBSERVED, source="test"),
    ]}
    combined = InMemoryLeanSampleStore(
        contracts={**daily.contracts, intraday_id: intraday_contract}, lifecycles=daily.lifecycles,
        quotes={**daily.quotes, **intraday_quotes}, trades=daily.trades, open_interest=daily.open_interest, underlying=daily.underlying,
    )
    ids = select_contracts_by_daily_richness(combined, max_per_underlying=10)
    assert daily_id in ids
    assert intraday_id not in ids


def test_build_panel_rows_defaults_to_richness_based_selection():
    """When both a rich and a sparse contract exist and the cap only
    fits one, the default selector must keep the RICHER one -- unlike
    plain evenly-strided ID order, which could pick either."""
    richer = synthetic_daily_multi_bar_store(n_bars=10, strike=100.0)
    sparser = synthetic_daily_multi_bar_store(n_bars=2, strike=999.0)  # sorts after richer's id either way
    from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
    combined = InMemoryLeanSampleStore(
        contracts={**richer.contracts, **sparser.contracts}, lifecycles={**richer.lifecycles, **sparser.lifecycles},
        quotes={**richer.quotes, **sparser.quotes}, trades={**richer.trades, **sparser.trades},
        open_interest={**richer.open_interest, **sparser.open_interest}, underlying=richer.underlying,
    )
    rows = build_panel_rows(combined, max_contracts_per_underlying=1)
    assert len(rows) == 10
    assert all(r["option_id"] == next(iter(richer.contracts)) for r in rows)


def test_subset_store_preserves_real_observations_unchanged():
    store = synthetic_daily_multi_bar_store(n_bars=4)
    cid = next(iter(store.contracts))
    small = subset_store(store, [cid])
    assert small.contracts[cid] == store.contracts[cid]
    assert small.quotes[cid] == store.quotes[cid]
    assert "AAPL" in small.underlying


def test_underlying_series_and_trailing_return():
    store = synthetic_daily_multi_bar_store(n_bars=5)
    series = build_underlying_series(store, "AAPL")
    assert len(series) == 5
    d1 = series[1][0]
    ret = underlying_trailing_return(series, d1, lag=1)
    assert ret is not None
    expected = (series[1][1] - series[0][1]) / series[0][1]
    assert ret == expected


def test_underlying_forward_returns_at_respects_horizon_availability():
    store = synthetic_daily_multi_bar_store(n_bars=5)
    series = build_underlying_series(store, "AAPL")
    d0 = series[0][0]
    fwd = underlying_forward_returns_at(series, d0, (1, 3, 10))
    assert fwd[1] is not None
    assert fwd[3] is not None
    assert fwd[10] is None  # not enough real future observations


def test_build_panel_rows_basic_shape():
    store = synthetic_daily_multi_bar_store(n_bars=8)
    rows = build_panel_rows(store, horizons=(1, 3, 5))
    assert len(rows) == 8
    for r in rows:
        assert r["underlying_symbol"] == "AAPL"
        assert r["symbol"] == "AAPL"
        assert r["call_put"] == "call"
        assert r["call_put_numeric"] == 1.0
        assert "forward_option_return_1" in r
        assert "mfe_5" in r
        assert "relative_to_underlying_3" in r
        assert "cs_group_key" in r


def test_last_row_has_no_forward_targets_never_fabricated():
    store = synthetic_daily_multi_bar_store(n_bars=6)
    rows = build_panel_rows(store, horizons=(1, 5))
    last = rows[-1]
    assert last["forward_option_return_1"] is None
    assert last["mfe_5"] is None


def test_first_row_has_no_option_daily_return_or_underlying_daily_return():
    store = synthetic_daily_multi_bar_store(n_bars=6)
    rows = build_panel_rows(store)
    first = rows[0]
    assert first["option_daily_return"] is None
    assert first["underlying_daily_return"] is None


def test_moneyness_uses_the_legacy_underlying_over_strike_convention():
    store = synthetic_daily_multi_bar_store(n_bars=1, strike=100.0)
    rows = build_panel_rows(store)
    row = rows[0]
    # underlying_price=185.0 for bar 0 in the fixture, strike=100.0 -> ratio > 1 (deep ITM call).
    assert row["moneyness_ratio"] > 1.0
    assert row["log_moneyness"] > 0.0


def test_relative_features_computed_within_peer_group():
    store = synthetic_daily_multi_bar_store(n_bars=4)
    rows = build_panel_rows(store)
    for r in rows[1:]:  # first row has no option_daily_return, so no relative_option_strength
        if r["option_daily_return"] is not None:
            assert "relative_option_strength" in r
        assert 0.0 <= r["relative_price_rank"] <= 1.0 or r["relative_price_rank"] is None


def test_daily_only_excludes_intraday_rows():
    """A contract whose only real observations are intraday (minute)
    contributes zero rows to the daily panel."""
    from datetime import datetime, timezone
    from src.data.source_profile import DataProvenance
    from src.data.store_interfaces import ProvenancedObservation
    from src.data.timestamp_model import EventTimestamps
    from src.options.phase26_dataset_builder import (
        InMemoryLeanSampleStore, build_contract_identity, build_provenance,
    )
    from src.options.phase26_lean_sample_parser import LeanContractFileMeta

    provenance = build_provenance(retrieval_timestamp=datetime(2026, 9, 4, tzinfo=timezone.utc), adjustment_status="x")
    meta = LeanContractFileMeta("SPY", "call", 400.0, date(2026, 12, 18), "quote", "american", None)
    contract = build_contract_identity(meta, provenance)
    cid = contract.option_id
    ts = datetime(2026, 8, 1, 14, 30, tzinfo=timezone.utc)  # intraday, not midnight
    quotes = {cid: [
        ProvenancedObservation(key=cid, field="bid", value=1.0, timestamps=EventTimestamps(event_time=ts), provenance=DataProvenance.OBSERVED, source="test"),
        ProvenancedObservation(key=cid, field="ask", value=1.1, timestamps=EventTimestamps(event_time=ts), provenance=DataProvenance.OBSERVED, source="test"),
    ]}
    store = InMemoryLeanSampleStore(contracts={cid: contract}, lifecycles={}, quotes=quotes, trades={}, open_interest={}, underlying={})
    rows = build_panel_rows(store)
    assert rows == []


def test_underlyings_with_daily_coverage_helper():
    store = synthetic_daily_multi_bar_store(n_bars=3)
    rows = build_panel_rows(store)
    assert underlyings_with_daily_coverage(rows) == ("AAPL",)
