"""Phase 39, Part 1-9/17 — the controlled live research runner: the
shared StaticHoodClient loader, the runner script's plumbing, restart
behavior, duplicate detection, partial/failed responses, rate limits,
empty chains, missing quotes, and market-hours gating.

The runner script itself (scripts/run_live_research_cycle.py) is a thin
CLI wrapper; these tests exercise the same underlying calls it makes
(load_static_hood_client_from_dir + run_observation_cycle +
default_recorder_stores) directly, since the script's own body is just
argument parsing and printing around those already-tested functions --
exactly matching how tests/test_phase38_campaign.py tests
run_phase38_campaign rather than a CLI wrapper around it.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.config.settings import Settings
from src.live_bridge import StaticHoodClient, load_static_hood_client_from_dir
from src.market.data_provider import MarketDataProvider
from src.market.hood_provider import HoodMarketDataProvider
from src.options.phase38_campaign import default_recorder_stores
from src.research_recorder.recorder import (
    MARKET_CLOSED,
    RecorderStores,
    run_observation_cycle,
)
from src.research_recorder.storage import (
    CycleLogStore,
    NormalizedOptionStore,
    NormalizedUnderlyingStore,
    RawObservationStore,
    ResearchSignalStore,
)

NOW = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)  # Tuesday, within regular hours
SATURDAY = datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc)


def _settings():
    return Settings.from_env(env={"TRADING_MODE": "paper"})


def _stores(tmp_path):
    return RecorderStores(
        raw=RawObservationStore(tmp_path / "raw.jsonl"), underlying=NormalizedUnderlyingStore(tmp_path / "underlying.jsonl"),
        option=NormalizedOptionStore(tmp_path / "option.jsonl"), signal=ResearchSignalStore(tmp_path / "signal.jsonl"),
        cycle_log=CycleLogStore(tmp_path / "cycle_log.jsonl"),
    )


# --- load_static_hood_client_from_dir (shared loader) ------------------------------------------


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj))


def test_loader_records_equity_and_option_quotes_and_chains():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        _write_json(d / "equity_quotes_AAPL.json", {"data": {"results": [{"quote": {"symbol": "AAPL"}}]}})
        _write_json(d / "option_chains_AAPL.json", {"data": {"chains": [{"id": "chain-1"}]}})
        _write_json(d / "option_instruments_chain-1.json", {"data": {"instruments": [{"id": "opt-1"}], "next": None}})
        _write_json(d / "option_quotes_opt-1.json", {"data": {"results": [{"quote": {"instrument_id": "opt-1"}}]}})

        client = load_static_hood_client_from_dir(d)
        assert client.get_equity_quotes(["AAPL"])["data"]["results"][0]["quote"]["symbol"] == "AAPL"
        assert client.get_option_chains(underlying_symbol="AAPL")["data"]["chains"][0]["id"] == "chain-1"
        assert client.get_option_instruments(chain_id="chain-1")["data"]["instruments"][0]["id"] == "opt-1"
        assert client.get_option_quotes(["opt-1"])["data"]["results"][0]["quote"]["instrument_id"] == "opt-1"


def test_loader_skips_option_positions_without_account_number():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        _write_json(d / "option_positions.json", {"data": {"results": []}})
        client = load_static_hood_client_from_dir(d, account_number=None)
        with pytest.raises(KeyError):
            client.get_option_positions("12345")


def test_loader_ignores_unrecognized_files():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        _write_json(d / "not_a_recognized_prefix.json", {"anything": True})
        client = load_static_hood_client_from_dir(d)
        assert isinstance(client, StaticHoodClient)


def test_static_client_raises_a_clear_error_for_unrecorded_calls():
    client = StaticHoodClient()
    with pytest.raises(KeyError, match="get_equity_quotes"):
        client.get_equity_quotes(["AAPL"])


# --- Multi-page instrument merge (Part 8's documented convention) -----------------------------


def test_merged_multi_page_instruments_file_avoids_the_pagination_replay_bug():
    """StaticHoodClient keys get_option_instruments by chain_id alone, not
    cursor -- a real multi-page response MUST be merged into one file with
    next=null before recording, exactly as scripts/run_live_research_cycle.py's
    docstring instructs; this proves that merged shape actually terminates
    pagination on the first call rather than looping."""
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        merged_instruments = [{"id": f"opt-{i}"} for i in range(50)]
        _write_json(d / "option_instruments_chain-1.json", {"data": {"instruments": merged_instruments, "next": None}})
        client = load_static_hood_client_from_dir(d)
        response = client.get_option_instruments(chain_id="chain-1", cursor="anything")
        assert len(response["data"]["instruments"]) == 50
        assert response["data"]["next"] is None


# --- Runner invocation end-to-end (market open) ------------------------------------------------


class _FakeClient:
    def __init__(self, *, option_fail_times=0):
        self.option_calls = 0
        self._option_fail_times = option_fail_times

    def get_equity_quotes(self, symbols):
        return {"data": {"results": [{
            "quote": {"symbol": symbols[0], "bid_price": "229.0", "ask_price": "231.0", "last_trade_price": "230.0", "venue_last_trade_time": NOW.isoformat()},
            "close": {"price": "228.0"},
        }]}}

    def get_option_quotes(self, instrument_ids):
        self.option_calls += 1
        if self.option_calls <= self._option_fail_times:
            raise RuntimeError("simulated rate limit")
        results = [{"quote": {
            "instrument_id": oid, "bid_price": "1.0", "ask_price": "1.05", "bid_size": "5", "ask_size": "7",
            "mark_price": "1.02", "volume": "100", "open_interest": "200", "implied_volatility": "0.3",
            "delta": "0.5", "updated_at": NOW.isoformat(),
        }} for oid in instrument_ids]
        return {"data": {"results": results}}


class _FakeMarket(MarketDataProvider):
    def __init__(self, *, chain_candidates=None):
        self._chain_candidates = chain_candidates

    def get_market_snapshot(self, option_id, underlying_symbol, now=None): raise NotImplementedError
    def get_underlying_snapshot(self, symbol, now=None): raise NotImplementedError
    def get_option_expirations(self, underlying_symbol): return [(NOW.date() + timedelta(days=30))]

    def get_option_chain_candidates(self, underlying_symbol, **filters):
        if self._chain_candidates is not None:
            return self._chain_candidates
        return [
            {"id": f"opt-{underlying_symbol}-{strike}", "type": "call", "strike_price": str(strike),
             "expiration_date": (NOW.date() + timedelta(days=30)).isoformat(), "state": "active", "tradability": "tradable"}
            for strike in (220, 230, 240)
        ]


def test_runner_invocation_records_a_real_cycle_end_to_end():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        result = run_observation_cycle(client=_FakeClient(), market=_FakeMarket(), settings=_settings(), stores=stores, now=NOW, universe=["AAPL"])
        assert result != MARKET_CLOSED
        assert result.symbol_results[0].succeeded
        assert result.symbol_results[0].contracts_observed > 0
        assert len(stores.option.load_all_raw_dicts()) > 0


def test_runner_via_default_recorder_stores_matches_phase38s_documented_path(tmp_path):
    stores = default_recorder_stores(tmp_path / "phase37_data")
    result = run_observation_cycle(client=_FakeClient(), market=_FakeMarket(), settings=_settings(), stores=stores, now=NOW, universe=["AAPL"])
    assert result != MARKET_CLOSED
    assert (tmp_path / "phase37_data" / "raw_observations.jsonl").is_file()


# --- Market-hours behavior ----------------------------------------------------------------------


def test_runner_exits_cleanly_on_a_weekend_with_zero_observations_recorded():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        result = run_observation_cycle(client=_FakeClient(), market=_FakeMarket(), settings=_settings(), stores=stores, now=SATURDAY, universe=["AAPL"])
        assert result == MARKET_CLOSED
        assert stores.raw.load_all() == []
        assert stores.option.load_all_raw_dicts() == []


# --- Restart-safety / duplicate detection -------------------------------------------------------


def test_restart_with_the_same_cycle_id_never_duplicates_data():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        run_observation_cycle(client=_FakeClient(), market=_FakeMarket(), settings=_settings(), stores=stores, now=NOW, universe=["AAPL"], cycle_id="cyc-fixed")
        n_after_first = len(stores.option.load_all_raw_dicts())

        # Simulate a crash + restart: a FRESH set of store instances pointed
        # at the SAME files, re-processing the SAME cycle_id.
        stores2 = RecorderStores(
            raw=RawObservationStore(Path(d) / "raw.jsonl"), underlying=NormalizedUnderlyingStore(Path(d) / "underlying.jsonl"),
            option=NormalizedOptionStore(Path(d) / "option.jsonl"), signal=ResearchSignalStore(Path(d) / "signal.jsonl"),
            cycle_log=CycleLogStore(Path(d) / "cycle_log.jsonl"),
        )
        run_observation_cycle(client=_FakeClient(), market=_FakeMarket(), settings=_settings(), stores=stores2, now=NOW, universe=["AAPL"], cycle_id="cyc-fixed")
        assert len(stores2.option.load_all_raw_dicts()) == n_after_first


# --- Partial responses / API errors / rate limits -----------------------------------------------


def test_partial_option_quote_failure_is_recorded_not_silently_dropped():
    from src.research_recorder.recorder import RecorderConfig

    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        result = run_observation_cycle(
            client=_FakeClient(option_fail_times=99), market=_FakeMarket(), settings=_settings(), stores=stores, now=NOW, universe=["AAPL"],
            config=RecorderConfig(max_retries=0, retry_backoff_seconds=0.0), sleep_fn=lambda s: None,
        )
        assert result != MARKET_CLOSED
        assert not result.symbol_results[0].succeeded
        assert "failed" in result.symbol_results[0].failure_reason.lower()


def test_empty_chain_is_recorded_as_a_named_failure_not_a_crash():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        result = run_observation_cycle(
            client=_FakeClient(), market=_FakeMarket(chain_candidates=[]), settings=_settings(), stores=stores, now=NOW, universe=["AAPL"],
        )
        assert result != MARKET_CLOSED
        assert not result.symbol_results[0].succeeded
        assert "chain" in result.symbol_results[0].failure_reason.lower() or "candidates" in result.symbol_results[0].failure_reason.lower()


def test_missing_underlying_quote_is_recorded_as_a_named_failure():
    class _NoQuoteClient(_FakeClient):
        def get_equity_quotes(self, symbols):
            return {"data": {"results": []}}  # symbol never matched -- exactly how a real unresolved symbol looks

    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        result = run_observation_cycle(client=_NoQuoteClient(), market=_FakeMarket(), settings=_settings(), stores=stores, now=NOW, universe=["AAPL"])
        assert result != MARKET_CLOSED
        assert not result.symbol_results[0].succeeded


def test_a_transient_api_failure_recovers_via_the_recorders_own_bounded_retry():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        from src.research_recorder.recorder import RecorderConfig

        result = run_observation_cycle(
            client=_FakeClient(option_fail_times=1), market=_FakeMarket(), settings=_settings(), stores=stores, now=NOW, universe=["AAPL"],
            config=RecorderConfig(max_retries=2, retry_backoff_seconds=0.0), sleep_fn=lambda s: None,
        )
        assert result != MARKET_CLOSED
        assert result.symbol_results[0].succeeded  # recovered within the retry budget


def test_a_malformed_contract_missing_an_id_is_skipped_not_crashed():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        malformed = [{"type": "call", "strike_price": "230.0", "expiration_date": (NOW.date() + timedelta(days=30)).isoformat()}]  # no "id"
        result = run_observation_cycle(
            client=_FakeClient(), market=_FakeMarket(chain_candidates=malformed), settings=_settings(), stores=stores, now=NOW, universe=["AAPL"],
        )
        assert result != MARKET_CLOSED
        assert not result.symbol_results[0].succeeded  # no usable option_id -- a named failure, never a crash


# --- Symbol subset / universe handling -----------------------------------------------------------


def test_runner_records_actual_availability_never_fabricates_a_missing_symbol():
    from src.research_recorder.recorder import RecorderConfig

    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        result = run_observation_cycle(
            client=_FakeClient(option_fail_times=99), market=_FakeMarket(), settings=_settings(), stores=stores, now=NOW,
            universe=["AAPL", "NVDA"], config=RecorderConfig(max_retries=0, retry_backoff_seconds=0.0), sleep_fn=lambda s: None,
        )
        symbols_seen = {sr.symbol for sr in result.symbol_results}
        assert symbols_seen == {"AAPL", "NVDA"}
        assert all(not sr.succeeded for sr in result.symbol_results)  # both genuinely failed -- recorded, not dropped
