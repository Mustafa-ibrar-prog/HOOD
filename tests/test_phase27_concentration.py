"""Phase 27, Part 13/16 — concentration/sample-balance measurement
against a small constructed fixture designed to have a KNOWN, checkable
concentration."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.data.source_profile import DataProvenance
from src.data.store_interfaces import ProvenancedObservation
from src.data.timestamp_model import EventTimestamps
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore, build_contract_identity, build_provenance
from src.options.phase26_lean_sample_parser import LeanContractFileMeta
from src.options.phase27_concentration import build_concentration_report

RETRIEVAL = datetime(2026, 9, 3, tzinfo=timezone.utc)


def _obs(key, field, value, ts):
    return ProvenancedObservation(key=key, field=field, value=value,
                                   timestamps=EventTimestamps(event_time=ts, observation_time=ts),
                                   provenance=DataProvenance.OBSERVED, source="test")


def _build_skewed_fixture():
    """3 AAPL contracts (2 calls, 1 put) and 1 SPY contract (1 call) --
    a known, hand-checkable 75%/25% underlying split."""
    p = build_provenance(retrieval_timestamp=RETRIEVAL, adjustment_status="x")
    contracts = {}
    quotes = {}
    for strike, right in [(100.0, "call"), (110.0, "call"), (100.0, "put")]:
        meta = LeanContractFileMeta("AAPL", right, strike, date(2016, 1, 15), "quote", "american", None)
        c = build_contract_identity(meta, p)
        contracts[c.option_id] = c
        quotes[c.option_id] = [_obs(c.option_id, "bid", 1.0, datetime(2015, 1, 2))]
    meta_spy = LeanContractFileMeta("SPY", "call", 430.0, date(2023, 9, 1), "quote", "american", None)
    c_spy = build_contract_identity(meta_spy, p)
    contracts[c_spy.option_id] = c_spy
    quotes[c_spy.option_id] = [_obs(c_spy.option_id, "bid", 1.0, datetime(2023, 8, 3))]
    store = InMemoryLeanSampleStore(contracts=contracts, lifecycles={}, quotes=quotes, trades={}, open_interest={}, underlying={})
    return store


def test_top_underlying_percentage_is_correct():
    store = _build_skewed_fixture()
    rep = build_concentration_report(store, moneyness_by_underlying=lambda u, s: "bucket")
    assert rep.top_underlying == "AAPL"
    assert rep.top_underlying_pct == 0.75


def test_call_put_ratio_is_correct():
    store = _build_skewed_fixture()
    rep = build_concentration_report(store, moneyness_by_underlying=lambda u, s: "bucket")
    # 3 calls (AAPL x2, SPY x1), 1 put (AAPL)
    assert rep.call_put_ratio == 3.0


def test_n_underlyings_counts_distinct_symbols():
    store = _build_skewed_fixture()
    rep = build_concentration_report(store, moneyness_by_underlying=lambda u, s: "bucket")
    assert rep.n_underlyings == 2


def test_call_put_ratio_is_none_when_no_puts():
    p = build_provenance(retrieval_timestamp=RETRIEVAL, adjustment_status="x")
    meta = LeanContractFileMeta("AAPL", "call", 100.0, date(2016, 1, 15), "quote", "american", None)
    c = build_contract_identity(meta, p)
    store = InMemoryLeanSampleStore(contracts={c.option_id: c}, lifecycles={}, quotes={}, trades={}, open_interest={}, underlying={})
    rep = build_concentration_report(store, moneyness_by_underlying=lambda u, s: "bucket")
    assert rep.call_put_ratio is None


def test_top_sector_reflects_the_real_sector_map():
    store = _build_skewed_fixture()
    rep = build_concentration_report(store, moneyness_by_underlying=lambda u, s: "bucket")
    assert rep.top_sector == "technology"  # AAPL dominates at 75%


def test_empty_store_reports_zero_concentration_without_crashing():
    store = InMemoryLeanSampleStore(contracts={}, lifecycles={}, quotes={}, trades={}, open_interest={}, underlying={})
    rep = build_concentration_report(store, moneyness_by_underlying=lambda u, s: "bucket")
    assert rep.n_underlyings == 0
    assert rep.top_underlying_pct == 0.0
