"""Phase 18, Part 22/4 — options store tests: round-trip persistence,
Protocol interop, and the explicit "no unsupported functionality
pretends to work" contract for historical methods."""

from __future__ import annotations

from datetime import date

import pytest

from src.data.store_interfaces import OptionsStore as GenericOptionsStoreProtocol
from src.options.instrument import OptionContract
from src.options.store import HistoricalOptionsDataUnavailableError, OptionsDataStore, OptionsDataStoreError

CONTRACT = OptionContract(underlying_symbol="AAPL", option_id="c55a630e-a0b9-45ab-b889-47bee291fee7", call_put="call", strike=175.0, expiration=date(2022, 1, 21))


def test_contract_round_trip(tmp_path):
    store = OptionsDataStore(tmp_path)
    store.save_contracts("AAPL", [CONTRACT])
    loaded = store.load_contracts("AAPL")
    assert loaded == [CONTRACT]


def test_get_contract(tmp_path):
    store = OptionsDataStore(tmp_path)
    store.save_contracts("AAPL", [CONTRACT])
    found = store.get_contract(CONTRACT.option_id, underlying_symbol="AAPL")
    assert found == CONTRACT
    assert store.get_contract("nonexistent", underlying_symbol="AAPL") is None


def test_get_chain_filters_by_expiration(tmp_path):
    other = OptionContract(underlying_symbol="AAPL", option_id="other-id", call_put="put", strike=25.0, expiration=date(2022, 3, 18))
    store = OptionsDataStore(tmp_path)
    store.save_contracts("AAPL", [CONTRACT, other])
    only_jan = store.get_chain("AAPL", expiration=date(2022, 1, 21))
    assert only_jan == [CONTRACT]
    all_contracts = store.get_chain("AAPL")
    assert len(all_contracts) == 2


def test_missing_symbol_returns_empty(tmp_path):
    store = OptionsDataStore(tmp_path)
    assert store.load_contracts("ZZZZ") == []
    assert store.get_chain("ZZZZ") == []


def test_corrupted_contracts_file_raises(tmp_path):
    store = OptionsDataStore(tmp_path)
    path = tmp_path / "AAPL" / "option_contracts.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("{not valid json\n")
    with pytest.raises(OptionsDataStoreError):
        store.load_contracts("AAPL")


def test_get_historical_chain_raises_unavailable(tmp_path):
    store = OptionsDataStore(tmp_path)
    with pytest.raises(HistoricalOptionsDataUnavailableError):
        store.get_historical_chain("AAPL", as_of=date(2022, 1, 1))


def test_get_as_of_chain_raises_unavailable(tmp_path):
    from datetime import datetime, timezone

    store = OptionsDataStore(tmp_path)
    with pytest.raises(HistoricalOptionsDataUnavailableError):
        store.get_as_of_chain("AAPL", as_of=datetime(2022, 1, 1, tzinfo=timezone.utc))


def test_get_quotes_not_implemented(tmp_path):
    store = OptionsDataStore(tmp_path)
    with pytest.raises(NotImplementedError):
        store.get_quotes([CONTRACT.option_id], underlying_symbol="AAPL")


def test_save_generic_protocol_shape_not_implemented(tmp_path):
    store = OptionsDataStore(tmp_path)
    with pytest.raises(NotImplementedError):
        store.save("AAPL", [])


def test_store_satisfies_generic_options_store_protocol_shape(tmp_path):
    store = OptionsDataStore(tmp_path)
    assert isinstance(store, GenericOptionsStoreProtocol)


def test_load_via_generic_protocol_returns_provenanced_observations(tmp_path):
    store = OptionsDataStore(tmp_path)
    store.save_contracts("AAPL", [CONTRACT])
    observations = store.load("AAPL")
    assert len(observations) == 1
    assert observations[0].key == CONTRACT.option_id
