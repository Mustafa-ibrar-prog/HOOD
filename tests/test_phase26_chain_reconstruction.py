"""Phase 26, Part 5/15 — historical chain reconstruction, tested against
a constructed multi-contract fixture that mirrors the real structure
this phase found (a not-yet-listed strike, an already-expired contract,
and a currently-knowable one)."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.data.source_profile import DataProvenance
from src.data.store_interfaces import ProvenancedObservation
from src.data.timestamp_model import EventTimestamps
from src.options.historical_data_interfaces import ContractLifecycle, ContractLifecycleStatus
from src.options.phase26_chain_reconstruction import (
    contracts_incorrectly_visible_before_first_observation,
    reconstruct_chain_as_of,
)
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore, build_contract_identity, build_provenance
from src.options.phase26_lean_sample_parser import LeanContractFileMeta

RETRIEVAL = datetime(2026, 9, 3, tzinfo=timezone.utc)


def _obs(key, field, value, ts):
    return ProvenancedObservation(key=key, field=field, value=value,
                                   timestamps=EventTimestamps(event_time=ts, observation_time=ts),
                                   provenance=DataProvenance.OBSERVED, source="test")


def _build_three_contract_fixture():
    p = build_provenance(retrieval_timestamp=RETRIEVAL, adjustment_status="x")

    # Contract A: knowable as of the probe date (real, active quote history through it)
    meta_a = LeanContractFileMeta("AAPL", "call", 100.0, date(2016, 1, 15), "quote", "american", None)
    c_a = build_contract_identity(meta_a, p)
    lc_a = ContractLifecycle(c_a.option_id, date(2015, 1, 2), None, date(2015, 12, 31), date(2016, 1, 15), ContractLifecycleStatus.UNKNOWN, p)

    # Contract B: not yet observed as of the probe date (first_observable_date is AFTER it)
    meta_b = LeanContractFileMeta("AAPL", "call", 200.0, date(2016, 1, 15), "quote", "american", None)
    c_b = build_contract_identity(meta_b, p)
    lc_b = ContractLifecycle(c_b.option_id, date(2015, 9, 1), None, date(2015, 12, 31), date(2016, 1, 15), ContractLifecycleStatus.UNKNOWN, p)

    # Contract C: already expired as of the probe date
    meta_c = LeanContractFileMeta("AAPL", "call", 90.0, date(2015, 3, 20), "quote", "american", None)
    c_c = build_contract_identity(meta_c, p)
    lc_c = ContractLifecycle(c_c.option_id, date(2015, 1, 2), None, date(2015, 3, 19), date(2015, 3, 20), ContractLifecycleStatus.EXPIRED, p)

    quotes = {
        c_a.option_id: [_obs(c_a.option_id, "bid", 1.0, datetime(2015, 6, 1))],
        c_b.option_id: [_obs(c_b.option_id, "bid", 1.0, datetime(2015, 9, 5))],
        c_c.option_id: [_obs(c_c.option_id, "bid", 1.0, datetime(2015, 3, 1))],
    }
    store = InMemoryLeanSampleStore(
        contracts={c_a.option_id: c_a, c_b.option_id: c_b, c_c.option_id: c_c},
        lifecycles={c_a.option_id: lc_a, c_b.option_id: lc_b, c_c.option_id: lc_c},
        quotes=quotes, trades={}, open_interest={}, underlying={},
    )
    return store, c_a, c_b, c_c


def test_reconstruction_includes_only_the_knowable_contract():
    store, c_a, c_b, c_c = _build_three_contract_fixture()
    as_of = datetime(2015, 6, 15)
    result = reconstruct_chain_as_of(store, "AAPL", as_of)
    included_ids = {c.option_id for c in result.reconstructed_contracts}
    assert included_ids == {c_a.option_id}


def test_reconstruction_excludes_not_yet_observed_contract():
    store, c_a, c_b, c_c = _build_three_contract_fixture()
    result = reconstruct_chain_as_of(store, "AAPL", datetime(2015, 6, 15))
    assert c_b.option_id in result.excluded_not_yet_observed


def test_reconstruction_excludes_already_expired_contract():
    store, c_a, c_b, c_c = _build_three_contract_fixture()
    result = reconstruct_chain_as_of(store, "AAPL", datetime(2015, 6, 15))
    assert c_c.option_id in result.excluded_already_expired


def test_no_violations_in_a_correctly_reconstructed_chain():
    store, *_ = _build_three_contract_fixture()
    violations = contracts_incorrectly_visible_before_first_observation(store, "AAPL", datetime(2015, 6, 15))
    assert violations == ()


def test_reconstruction_is_symbol_scoped():
    store, c_a, c_b, c_c = _build_three_contract_fixture()
    result = reconstruct_chain_as_of(store, "SPY", datetime(2015, 6, 15))
    assert result.reconstructed_contracts == ()
    assert result.excluded_not_yet_observed == ()
    assert result.excluded_already_expired == ()
