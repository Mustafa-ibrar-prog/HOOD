"""Phase 37, Part 20-22/24 — the recorder orchestration, storage
restart-safety/duplicate-detection, retry/backoff, and research-signal
recording."""

from __future__ import annotations

import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.config.settings import Settings
from src.market.data_provider import MarketDataProvider
from src.production.decision import DecisionType
from src.research_recorder.recorder import (
    MARKET_CLOSED,
    RecorderConfig,
    RecorderStores,
    run_observation_cycle,
)
from src.research_recorder.research_signal import ResultLabel, evaluate_research_signal_for_cycle
from src.research_recorder.storage import (
    CycleLogStore,
    NormalizedOptionStore,
    NormalizedUnderlyingStore,
    RawObservationStore,
    ResearchSignalStore,
)

NOW = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)  # Tuesday, within regular hours


def _settings():
    return Settings.from_env(env={"TRADING_MODE": "paper"})


class FakeClient:
    def __init__(self, *, equity_fail_times=0, option_fail_times=0):
        self.equity_calls = 0
        self.option_calls = 0
        self._equity_fail_times = equity_fail_times
        self._option_fail_times = option_fail_times

    def get_equity_quotes(self, symbols):
        self.equity_calls += 1
        if self.equity_calls <= self._equity_fail_times:
            raise RuntimeError("simulated API failure")
        return {"data": {"results": [{
            "quote": {"symbol": symbols[0], "bid_price": None, "ask_price": None, "last_trade_price": "230.0", "venue_last_trade_time": NOW.isoformat()},
            "close": {"price": "228.0"},
        }]}}

    def get_option_quotes(self, instrument_ids):
        self.option_calls += 1
        if self.option_calls <= self._option_fail_times:
            raise RuntimeError("simulated API failure")
        results = [{"quote": {
            "instrument_id": oid, "bid_price": "1.0", "ask_price": "1.05", "bid_size": "5", "ask_size": "7",
            "mark_price": "1.02", "volume": "100", "open_interest": "200", "implied_volatility": "0.3",
            "delta": "0.5", "updated_at": NOW.isoformat(),
        }} for oid in instrument_ids]
        return {"data": {"results": results}}


class FakeMarket(MarketDataProvider):
    def __init__(self, *, chain_candidates=None, expirations=None):
        self._chain_candidates = chain_candidates
        self._expirations = expirations or [(NOW.date() + timedelta(days=30))]

    def get_market_snapshot(self, option_id, underlying_symbol, now=None):
        raise NotImplementedError

    def get_underlying_snapshot(self, symbol, now=None):
        raise NotImplementedError

    def get_option_expirations(self, underlying_symbol):
        return self._expirations

    def get_option_chain_candidates(self, underlying_symbol, **filters):
        if self._chain_candidates is not None:
            return self._chain_candidates
        return [
            {"id": f"opt-{underlying_symbol}-{strike}", "type": "call", "strike_price": str(strike),
             "expiration_date": (NOW.date() + timedelta(days=30)).isoformat(), "state": "active", "tradability": "tradable"}
            for strike in (220, 230, 240)
        ]


def _stores(tmp_path):
    return RecorderStores(
        raw=RawObservationStore(tmp_path / "raw.jsonl"),
        underlying=NormalizedUnderlyingStore(tmp_path / "underlying.jsonl"),
        option=NormalizedOptionStore(tmp_path / "option.jsonl"),
        signal=ResearchSignalStore(tmp_path / "signal.jsonl"),
        cycle_log=CycleLogStore(tmp_path / "cycle_log.jsonl"),
    )


# --- Market hours ------------------------------------------------------------------------------


def test_market_closed_returns_sentinel_and_calls_nothing(tmp_path):
    client = FakeClient()
    saturday = datetime(2026, 8, 15, 15, 0, tzinfo=timezone.utc)
    result = run_observation_cycle(
        client=client, market=FakeMarket(), settings=_settings(), stores=_stores(tmp_path), now=saturday, universe=["AAPL"],
    )
    assert result == MARKET_CLOSED
    assert client.equity_calls == 0


# --- Successful cycle -----------------------------------------------------------------------


def test_successful_cycle_records_everything():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        result = run_observation_cycle(client=FakeClient(), market=FakeMarket(), settings=_settings(), stores=stores, now=NOW, universe=["AAPL", "MSFT"])
        assert result != MARKET_CLOSED
        assert len(result.symbol_results) == 2
        assert all(r.succeeded for r in result.symbol_results)
        assert len(stores.option.load_all_raw_dicts()) == 6  # 3 contracts x 2 symbols
        assert len(stores.raw.load_all()) == 4  # 1 equity + 1 option call per symbol


# --- API failure / retry ---------------------------------------------------------------------


def test_api_failure_recorded_not_crashed():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        client = FakeClient(equity_fail_times=99)  # always fails
        result = run_observation_cycle(
            client=client, market=FakeMarket(), settings=_settings(), stores=stores, now=NOW, universe=["AAPL"],
            config=RecorderConfig(max_retries=1, retry_backoff_seconds=0.0), sleep_fn=lambda s: None,
        )
        assert not result.symbol_results[0].succeeded
        assert "get_equity_quotes failed" in result.symbol_results[0].failure_reason


def test_retry_recovers_from_a_transient_failure():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        client = FakeClient(equity_fail_times=1)  # fails once, then succeeds
        result = run_observation_cycle(
            client=client, market=FakeMarket(), settings=_settings(), stores=stores, now=NOW, universe=["AAPL"],
            config=RecorderConfig(max_retries=2, retry_backoff_seconds=0.0), sleep_fn=lambda s: None,
        )
        assert result.symbol_results[0].succeeded
        assert client.equity_calls == 2  # one failure + one success


def test_retry_is_bounded_never_an_infinite_loop():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        client = FakeClient(equity_fail_times=99)
        run_observation_cycle(
            client=client, market=FakeMarket(), settings=_settings(), stores=stores, now=NOW, universe=["AAPL"],
            config=RecorderConfig(max_retries=3, retry_backoff_seconds=0.0), sleep_fn=lambda s: None,
        )
        assert client.equity_calls == 4  # 1 initial + 3 retries, never unbounded


def test_option_quote_api_failure_recorded():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        client = FakeClient(option_fail_times=99)
        result = run_observation_cycle(
            client=client, market=FakeMarket(), settings=_settings(), stores=stores, now=NOW, universe=["AAPL"],
            config=RecorderConfig(max_retries=0, retry_backoff_seconds=0.0), sleep_fn=lambda s: None,
        )
        assert not result.symbol_results[0].succeeded
        assert "get_option_quotes failed" in result.symbol_results[0].failure_reason


# --- Per-symbol failures are recorded, never silently dropped (Part 4) ------------------------


def test_symbol_with_no_chain_candidates_recorded_as_failed_not_dropped():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        market = FakeMarket(chain_candidates=[])
        result = run_observation_cycle(client=FakeClient(), market=market, settings=_settings(), stores=stores, now=NOW, universe=["AAPL"])
        assert len(result.symbol_results) == 1  # still present, not removed
        assert not result.symbol_results[0].succeeded
        assert result.symbol_results[0].symbol == "AAPL"


# --- Restart / recovery ------------------------------------------------------------------------


def test_restart_with_same_cycle_id_never_duplicates_data():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d)
        stores1 = _stores(path)
        result1 = run_observation_cycle(client=FakeClient(), market=FakeMarket(), settings=_settings(), stores=stores1, now=NOW, universe=["AAPL"])

        stores2 = _stores(path)  # simulates a fresh process after a restart
        result2 = run_observation_cycle(
            client=FakeClient(), market=FakeMarket(), settings=_settings(), stores=stores2, now=NOW, universe=["AAPL"],
            cycle_id=result1.observation_cycle_id,
        )
        assert len(stores2.option.load_all_raw_dicts()) == 3  # not 6 -- no duplicate rows
        assert result2.symbol_results[0].duplicates_detected == 3


def test_different_cycle_ids_do_not_collide():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        run_observation_cycle(client=FakeClient(), market=FakeMarket(), settings=_settings(), stores=stores, now=NOW, universe=["AAPL"], cycle_id="cyc-A")
        run_observation_cycle(client=FakeClient(), market=FakeMarket(), settings=_settings(), stores=stores, now=NOW, universe=["AAPL"], cycle_id="cyc-B")
        assert len(stores.option.load_all_raw_dicts()) == 6  # two distinct cycles, both recorded


def test_incomplete_cycle_then_restart_completes_remaining_symbols():
    """Simulates a crash after AAPL succeeded but before MSFT was
    attempted -- a restart with the same cycle_id must process MSFT
    without re-duplicating AAPL."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d)
        stores1 = _stores(path)
        run_observation_cycle(client=FakeClient(), market=FakeMarket(), settings=_settings(), stores=stores1, now=NOW, universe=["AAPL"], cycle_id="cyc-X")

        stores2 = _stores(path)
        run_observation_cycle(client=FakeClient(), market=FakeMarket(), settings=_settings(), stores=stores2, now=NOW, universe=["AAPL", "MSFT"], cycle_id="cyc-X")

        rows = stores2.option.load_all_raw_dicts()
        assert {r["underlying"] for r in rows} == {"AAPL", "MSFT"}
        assert len(rows) == 6  # 3 AAPL (not duplicated) + 3 MSFT (newly added)


# --- Duplicate detection at the storage layer (Part 20) --------------------------------------


def test_raw_store_detects_duplicate_across_restart(tmp_path):
    from src.research_recorder.raw_observation import RawObservation

    obs = RawObservation.build(observation_cycle_id="c1", provider="robinhood_hood_mcp", tool_name="get_option_quotes", retrieval_timestamp=NOW, market_timestamp=None, raw_payload={"a": 1})
    store1 = RawObservationStore(tmp_path / "raw.jsonl")
    assert store1.append(obs) is True
    assert store1.append(obs) is False

    store2 = RawObservationStore(tmp_path / "raw.jsonl")  # fresh instance, same file
    assert store2.append(obs) is False  # still detected after "restart"


# --- Research signal recording (Part 14/15) ---------------------------------------------------


def test_research_signal_labeled_hypothetical_never_trade_or_order():
    market = FakeMarket(chain_candidates=[])
    record = evaluate_research_signal_for_cycle(market=market, universe=["AAPL"], observation_cycle_id="c1", now=NOW)
    assert record.label == ResultLabel.HYPOTHETICAL_RESEARCH_DECISION.value
    for forbidden in ("TRADE", "ORDER", "POSITION", "FILL"):
        assert forbidden != record.label
        assert forbidden != record.decision


def test_research_signal_strategy_id_is_momentum_breakout():
    from src.options.phase35_frozen_strategy_spec import STRATEGY_ID

    market = FakeMarket(chain_candidates=[])
    record = evaluate_research_signal_for_cycle(market=market, universe=["AAPL"], observation_cycle_id="c1", now=NOW)
    assert record.strategy_id == STRATEGY_ID


def test_research_signal_evaluation_failure_handled_gracefully():
    class _RaisingMarket(MarketDataProvider):
        def get_market_snapshot(self, option_id, underlying_symbol, now=None):
            raise NotImplementedError

        def get_underlying_snapshot(self, symbol, now=None):
            raise RuntimeError("simulated market data failure")

        def get_option_expirations(self, underlying_symbol):
            raise NotImplementedError

        def get_option_chain_candidates(self, underlying_symbol, **filters):
            raise NotImplementedError

    record = evaluate_research_signal_for_cycle(market=_RaisingMarket(), universe=["AAPL"], observation_cycle_id="c1", now=NOW)
    assert record.produced_signal is False
    assert record.evaluation_error is not None
    assert record.decision == DecisionType.NO_TRADE.value


def test_research_signal_recorded_every_cycle_regardless_of_outcome():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        market = FakeMarket(chain_candidates=[])
        run_observation_cycle(client=FakeClient(), market=market, settings=_settings(), stores=stores, now=NOW, universe=["AAPL"])
        rows = stores.signal.load_all_raw_dicts()
        assert len(rows) == 1
        assert rows[0]["label"] == ResultLabel.HYPOTHETICAL_RESEARCH_DECISION.value
