"""Phase 39b — the fetch/save/merge operational glue that closes the gap
between "the agent can call real HOOD MCP tools" and "the recorder needs
files in an exact --data-dir convention". This is glue only: it never
calls a HOOD tool itself (nothing in this codebase can — see
src/market/hood_client.py's module docstring), never calls
run_observation_cycle, and never substitutes synthetic or historical
data for a missing real response.
"""

from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.config.settings import Settings
from src.live_bridge import (
    StaticHoodClient,
    load_static_hood_client_from_dir,
    merge_option_instrument_pages,
    save_hood_response_to_data_dir,
)
from src.market.data_provider import MarketDataProvider
from src.research_recorder.recorder import MARKET_CLOSED, RecorderStores, run_observation_cycle
from src.research_recorder.storage import CycleLogStore, NormalizedOptionStore, NormalizedUnderlyingStore, RawObservationStore, ResearchSignalStore

NOW = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)  # Tuesday, within regular hours
SATURDAY = datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc)


def _stores(tmp_path):
    return RecorderStores(
        raw=RawObservationStore(tmp_path / "raw.jsonl"), underlying=NormalizedUnderlyingStore(tmp_path / "underlying.jsonl"),
        option=NormalizedOptionStore(tmp_path / "option.jsonl"), signal=ResearchSignalStore(tmp_path / "signal.jsonl"),
        cycle_log=CycleLogStore(tmp_path / "cycle_log.jsonl"),
    )


# --- save_hood_response_to_data_dir --------------------------------------------------------------


def test_save_writes_the_exact_response_content_unmodified():
    with tempfile.TemporaryDirectory() as d:
        real_response = {"data": {"results": [{"quote": {"symbol": "SPY", "bid_price": "769.05"}}]}, "guide": "some real guide text"}
        path = save_hood_response_to_data_dir(Path(d), "equity_quotes_SPY", real_response)
        assert path.name == "equity_quotes_SPY.json"
        assert json.loads(path.read_text()) == real_response  # byte-for-byte round trip, nothing added/removed


def test_save_creates_the_data_dir_if_missing():
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "does" / "not" / "exist" / "yet"
        save_hood_response_to_data_dir(target, "equity_quotes_AAPL", {"data": {}})
        assert (target / "equity_quotes_AAPL.json").is_file()


def test_saved_file_loads_back_through_the_existing_loader():
    """Round-trips through the exact convention load_static_hood_client_from_dir
    already expects -- proves the write-side and read-side conventions agree."""
    with tempfile.TemporaryDirectory() as d:
        real_response = {"data": {"results": [{"quote": {"symbol": "SPY", "bid_price": "769.05"}}]}}
        save_hood_response_to_data_dir(Path(d), "equity_quotes_SPY", real_response)
        client = load_static_hood_client_from_dir(Path(d))
        assert client.get_equity_quotes(["SPY"]) == real_response


# --- merge_option_instrument_pages ----------------------------------------------------------------


def test_merge_concatenates_every_real_page_without_dropping_anything():
    page1 = {"data": {"instruments": [{"id": "opt-1"}, {"id": "opt-2"}], "next": "https://...cursor=abc"}, "guide": "g"}
    page2 = {"data": {"instruments": [{"id": "opt-3"}], "next": None}}
    merged = merge_option_instrument_pages([page1, page2])
    assert [i["id"] for i in merged["data"]["instruments"]] == ["opt-1", "opt-2", "opt-3"]
    assert merged["data"]["next"] is None
    assert merged["guide"] == "g"


def test_merge_of_a_single_page_is_a_no_op_content_wise():
    page = {"data": {"instruments": [{"id": "opt-1"}], "next": None}}
    merged = merge_option_instrument_pages([page])
    assert merged["data"]["instruments"] == [{"id": "opt-1"}]


def test_merged_result_terminates_pagination_on_first_replay_call():
    """The actual bug this exists to prevent: an un-merged multi-page
    recording would make _fetch_all_instruments loop, replaying page 1
    forever (bounded only by the 25-page safety cap)."""
    pages = [{"data": {"instruments": [{"id": f"opt-{i}"}], "next": f"...cursor={i}"}} for i in range(3)]
    merged = merge_option_instrument_pages(pages)
    with tempfile.TemporaryDirectory() as d:
        save_hood_response_to_data_dir(Path(d), "option_instruments_chain-1", merged)
        client = load_static_hood_client_from_dir(Path(d))
        response = client.get_option_instruments(chain_id="chain-1", cursor="anything")
        assert len(response["data"]["instruments"]) == 3
        assert response["data"]["next"] is None


def test_merge_never_fabricates_an_instrument_not_present_in_a_real_page():
    page1 = {"data": {"instruments": [{"id": "opt-1"}], "next": None}}
    merged = merge_option_instrument_pages([page1])
    assert merged["data"]["instruments"] == [{"id": "opt-1"}]
    assert "opt-2" not in json.dumps(merged)


# --- No synthetic fallback ------------------------------------------------------------------------


def test_static_client_never_returns_a_default_empty_response_for_an_unrecorded_call():
    """No synthetic fallback exists anywhere in this glue: an unrecorded
    call raises, it never silently returns {} or a fabricated shape."""
    client = StaticHoodClient()
    for method, args in (
        (client.get_equity_quotes, (["SPY"],)),
        (client.get_option_quotes, (["opt-1"],)),
        (client.get_option_chains, ()),
        (client.get_option_instruments, ()),
    ):
        with pytest.raises(KeyError):
            method(*args)


def test_loader_never_fabricates_a_missing_file_as_empty_data():
    with tempfile.TemporaryDirectory() as d:
        client = load_static_hood_client_from_dir(Path(d))  # empty dir -- nothing recorded
        with pytest.raises(KeyError):
            client.get_equity_quotes(["SPY"])


# --- No historical fallback ------------------------------------------------------------------------


def test_recorder_never_calls_get_equity_or_option_historicals():
    """Static source scan: the recorder must never substitute historical
    bars for a live quote/chain lookup."""
    source = (Path(__file__).resolve().parent.parent / "src/research_recorder/recorder.py").read_text()
    assert "get_equity_historicals" not in source
    assert "get_option_historicals" not in source


def test_static_client_keeps_historicals_and_quotes_strictly_separate():
    """record_equity_historicals must never satisfy a get_equity_quotes
    lookup, or vice versa -- proves there is no fallback path between
    them even at the StaticHoodClient level."""
    client = StaticHoodClient()
    client.record_equity_historicals("SPY", {"data": {"historicals": []}})
    with pytest.raises(KeyError):
        client.get_equity_quotes(["SPY"])  # historicals recorded, quotes were not -- must still raise


# --- Market-closed data cannot be recorded as a live observation -----------------------------------


class _FullyReadyClient:
    """A client that WOULD return complete, valid, real-shaped data --
    proves the market-hours refusal is about TIME, never about data
    availability."""

    def get_equity_quotes(self, symbols):
        return {"data": {"results": [{
            "quote": {"symbol": symbols[0], "bid_price": "229.0", "ask_price": "231.0", "last_trade_price": "230.0", "venue_last_trade_time": NOW.isoformat()},
            "close": {"price": "228.0"},
        }]}}

    def get_option_quotes(self, instrument_ids):
        results = [{"quote": {"instrument_id": oid, "bid_price": "1.0", "ask_price": "1.05", "updated_at": NOW.isoformat()}} for oid in instrument_ids]
        return {"data": {"results": results}}


class _FullyReadyMarket(MarketDataProvider):
    def get_market_snapshot(self, option_id, underlying_symbol, now=None): raise NotImplementedError
    def get_underlying_snapshot(self, symbol, now=None): raise NotImplementedError
    def get_option_expirations(self, underlying_symbol): return [(SATURDAY.date() + timedelta(days=30))]

    def get_option_chain_candidates(self, underlying_symbol, **filters):
        return [{"id": "opt-1", "type": "call", "strike_price": "230.0",
                 "expiration_date": (SATURDAY.date() + timedelta(days=30)).isoformat(), "state": "active", "tradability": "tradable"}]


def test_a_saturday_refuses_recording_even_with_fully_valid_ready_data():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        result = run_observation_cycle(
            client=_FullyReadyClient(), market=_FullyReadyMarket(), settings=Settings.from_env(env={"TRADING_MODE": "paper"}),
            stores=stores, now=SATURDAY, universe=["AAPL"],
        )
        assert result == MARKET_CLOSED
        assert stores.raw.load_all() == []
        assert stores.option.load_all_raw_dicts() == []


def test_the_recorder_not_the_data_source_decides_recordability():
    """Same fully-ready client/market, only `now` differs -- proves the
    gate is a pure function of time, and the glue functions above have no
    way to override it (they never call run_observation_cycle at all)."""
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        weekday_result = run_observation_cycle(
            client=_FullyReadyClient(), market=_FullyReadyMarket(), settings=Settings.from_env(env={"TRADING_MODE": "paper"}),
            stores=stores, now=NOW, universe=["AAPL"],
        )
        assert weekday_result != MARKET_CLOSED


def test_glue_functions_never_invoke_run_observation_cycle():
    """Static source scan: save/merge are passive file I/O only."""
    source = (Path(__file__).resolve().parent.parent / "src/live_bridge.py").read_text()
    assert "run_observation_cycle(" not in source


# --- Credentials, execution imports, order calls (extends existing Phase 39 safety coverage) ------


def test_no_credential_shaped_content_in_the_new_glue_functions():
    from src.research_recorder.security import assert_no_credential_shaped_content
    import inspect
    from src.live_bridge import merge_option_instrument_pages as _m, save_hood_response_to_data_dir as _s
    assert_no_credential_shaped_content(inspect.getsource(_s))
    assert_no_credential_shaped_content(inspect.getsource(_m))


def test_new_glue_functions_do_not_import_execution_gateway():
    import ast
    source = (Path(__file__).resolve().parent.parent / "src/live_bridge.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("src.execution.gateway")
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("src.execution.gateway")


def test_live_authorization_remains_off(tmp_path):
    from src.execution.system_state import SystemStateAuditLog, is_live_trading_authorized
    log = SystemStateAuditLog(tmp_path / "missing.jsonl")
    assert is_live_trading_authorized(log) is False


def test_emergency_stop_remains_active(tmp_path):
    from src.execution.emergency_stop import EmergencyStopStore
    assert EmergencyStopStore(tmp_path / "missing.json").is_stopped() is True
