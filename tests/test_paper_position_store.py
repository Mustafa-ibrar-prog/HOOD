from __future__ import annotations

import pytest

from src.position_manager.store import PaperPositionStore, PaperPositionStoreError
from tests.conftest import make_position


def test_load_returns_empty_list_when_no_file_exists(tmp_path):
    store = PaperPositionStore(tmp_path / "positions.json")
    assert store.load() == []


def test_add_and_load_round_trip(tmp_path):
    store = PaperPositionStore(tmp_path / "positions.json")
    position = make_position()
    store.add_position(position)

    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0].option_id == position.option_id
    assert loaded[0].entry_price == position.entry_price
    assert loaded[0].thesis.setup_name == position.thesis.setup_name


def test_add_position_rejects_duplicate_option_id(tmp_path):
    store = PaperPositionStore(tmp_path / "positions.json")
    position = make_position()
    store.add_position(position)
    with pytest.raises(PaperPositionStoreError):
        store.add_position(position)


def test_remove_position_removes_only_the_matching_one(tmp_path):
    store = PaperPositionStore(tmp_path / "positions.json")
    position_a = make_position(option_id="opt-a", symbol="AAPL")
    position_b = make_position(option_id="opt-b", symbol="MSFT")
    store.add_position(position_a)
    store.add_position(position_b)

    store.remove_position("opt-a")

    remaining = store.load()
    assert len(remaining) == 1
    assert remaining[0].option_id == "opt-b"


def test_remove_position_raises_when_not_found(tmp_path):
    store = PaperPositionStore(tmp_path / "positions.json")
    with pytest.raises(PaperPositionStoreError):
        store.remove_position("does-not-exist")


def test_corrupted_ledger_fails_closed(tmp_path):
    path = tmp_path / "positions.json"
    path.write_text("{not valid json")
    store = PaperPositionStore(path)
    with pytest.raises(PaperPositionStoreError):
        store.load()


def test_empty_file_is_treated_as_no_positions(tmp_path):
    path = tmp_path / "positions.json"
    path.write_text("")
    store = PaperPositionStore(path)
    assert store.load() == []


def test_multiple_positions_persist_independently(tmp_path):
    store = PaperPositionStore(tmp_path / "positions.json")
    for i in range(3):
        store.add_position(make_position(option_id=f"opt-{i}", symbol=f"SYM{i}"))
    assert len(store.load()) == 3
