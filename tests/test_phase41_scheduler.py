"""Phase 41 -- the automatic scheduler's own tick/loop behavior.

Uses the SAME `FakeMarketData`/`FakeClient`/`_bullish_market` fixture
shape `tests/test_phase40_engine.py` already established for a real
strategy entry, monkeypatched into `src.paper_trading.cycle_runner`'s
namespace so `run_scheduler_tick` exercises the REAL scheduler decision
logic (market-hours gate, slot dedup, event logging) around the REAL,
UNMODIFIED `run_paper_experiment_cycle` -> `run_trading_cycle` call
graph, exactly the same substitution point Phase 40's own engine tests
use one layer down.

Covers comprehensive-test-list items: 5 (market-open transition), 7
(restart behavior), 8 (duplicate-cycle prevention), 9 (partial symbol
failure), 10 (all-symbol failure), 11 (missing option quotes), 12
(malformed Robinhood response), 16 (experiment end-date enforcement), 19
(no fabricated data), 20 (open-position exit evaluation), 21 (repeated
intraday cycles), 22 (process restart while a position exists).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.live_bridge import save_hood_response_to_data_dir
from src.market.data_provider import MarketDataProvider
from src.market.errors import QuoteUnavailableError
from src.market.models import EquityQuote, MarketSnapshot, OptionQuote, UnderlyingSnapshot
from src.paper_trading.data_acquisition import AcquisitionResult, mark_inbox_slot_ready
from src.paper_trading.engine import experiment_paths
from src.paper_trading.experiment_config import ExperimentConfigStore, build_experiment_config
from src.paper_trading.market_calendar import slot_id_for
from src.paper_trading.scheduler import SchedulerConfig, build_event_store, run_scheduler_forever, run_scheduler_tick
from src.paper_trading.scheduler_events import (
    DATA_COLLECTION_FAILED,
    DATA_COLLECTION_PARTIAL,
    DATA_COLLECTION_STARTED,
    EXPERIMENT_COMPLETED,
    MARKET_OPEN,
    NO_QUALIFIED_OPPORTUNITY,
    PAPER_CYCLE_COMPLETED,
    PAPER_CYCLE_FAILED,
    PAPER_CYCLE_STARTED,
    PAPER_ENTRY,
    PAPER_SCHEDULER_STARTED,
    PAPER_SCHEDULER_STOPPED,
    SLOT_ALREADY_COMPLETED,
    WAITING_FOR_MARKET_OPEN,
)
from src.paper_trading.state_machine import ExperimentStateStore, ExperimentStatus

NOW = datetime(2026, 9, 8, 13, 30, tzinfo=timezone.utc)  # Tuesday, 9:30am ET -- market open
REAL_NOW = datetime.now(timezone.utc)


# --- fixtures reused/adapted from tests/test_phase40_engine.py ---------------------------------


def _bullish_underlying(symbol="AAPL") -> UnderlyingSnapshot:
    from tests.conftest import make_bars

    return UnderlyingSnapshot(
        quote=EquityQuote(symbol=symbol, last_trade_price=230.0, previous_close=225.0, as_of=NOW),
        bars=tuple(make_bars([220.0, 224.0, 228.0, 231.0])),
        rsi=62.0, rsi_prev=58.0, macd_histogram=0.10, macd_histogram_prev=0.05, ema_fast=230.5, ema_slow=225.0,
        vwap=228.0, volume_ratio=1.4, higher_highs=True, lower_highs=False, breakout_continuation=True,
        failed_breakout=False, fetched_at=REAL_NOW,
    )


def _liquid_option_snapshot(option_id, bid=1.00, ask=1.05) -> MarketSnapshot:
    return MarketSnapshot(
        option=OptionQuote(
            instrument_id=option_id, bid_price=bid, ask_price=ask, last_trade_price=(bid + ask) / 2,
            previous_close=0.90, volume=200, open_interest=500, as_of=NOW,
        ),
        underlying=EquityQuote(symbol="AAPL", last_trade_price=230.0, previous_close=225.0, as_of=NOW),
        option_bars=(), underlying_bars=(), rsi=None, rsi_prev=None, macd_histogram=None, macd_histogram_prev=None,
        ema_fast=None, ema_slow=None, vwap=None, volume_ratio=None, fetched_at=REAL_NOW,
    )


class FakeMarketData(MarketDataProvider):
    def __init__(self, *, underlying_snapshots=None, option_snapshots=None, expirations=None, chain_candidates=None):
        self.underlying_snapshots = underlying_snapshots or {}
        self.option_snapshots = option_snapshots or {}
        self.expirations = expirations or {}
        self.chain_candidates = chain_candidates or {}

    def get_market_snapshot(self, option_id, underlying_symbol, now=None):
        if option_id not in self.option_snapshots:
            raise QuoteUnavailableError(f"no snapshot configured for {option_id}")
        return self.option_snapshots[option_id]

    def get_underlying_snapshot(self, symbol, now=None):
        if symbol not in self.underlying_snapshots:
            raise QuoteUnavailableError(f"no snapshot configured for {symbol}")
        return self.underlying_snapshots[symbol]

    def get_option_expirations(self, underlying_symbol):
        return self.expirations.get(underlying_symbol, [])

    def get_option_chain_candidates(self, underlying_symbol, **filters):
        return self.chain_candidates.get(underlying_symbol, [])


class FakeClient:
    def __init__(self, *, equity_price=230.0, option_bid=1.00, option_ask=1.05):
        self._equity_price = equity_price
        self._option_bid = option_bid
        self._option_ask = option_ask

    def get_equity_quotes(self, symbols):
        return {"data": {"results": [
            {"quote": {"symbol": s, "bid_price": None, "ask_price": None, "last_trade_price": str(self._equity_price), "venue_last_trade_time": NOW.isoformat()}, "close": {"price": "225.0"}}
            for s in symbols
        ]}}

    def get_option_quotes(self, instrument_ids):
        results = [{"quote": {
            "instrument_id": oid, "bid_price": str(self._option_bid), "ask_price": str(self._option_ask),
            "bid_size": "5", "ask_size": "7", "mark_price": str((self._option_bid + self._option_ask) / 2),
            "volume": "200", "open_interest": "500", "implied_volatility": "0.3", "delta": "0.5",
            "updated_at": NOW.isoformat(),
        }} for oid in instrument_ids]
        return {"data": {"results": results}}

    def get_option_positions(self, account_number, nonzero=None, **kwargs):
        return {"data": {"positions": []}, "guide": "..."}

    def get_option_instruments(self, ids=None, **kwargs):
        return {"data": {"instruments": []}, "guide": "..."}


def _bullish_market(expiration=None):
    expiration = expiration or (NOW.date() + timedelta(days=14))
    return FakeMarketData(
        underlying_snapshots={"AAPL": _bullish_underlying()},
        expirations={"AAPL": [expiration]},
        chain_candidates={"AAPL": [{
            "id": "opt-aapl-1", "strike_price": "230.0000", "type": "call",
            "expiration_date": expiration.isoformat(), "state": "active", "tradability": "tradable",
        }]},
        option_snapshots={"opt-aapl-1": _liquid_option_snapshot("opt-aapl-1")},
    )


def _empty_market():
    return FakeMarketData()


class FakeAcquisitionProvider:
    """A fully controllable `DataAcquisitionProvider` for scheduler-tick
    tests -- unlike `InboxDataAcquisitionProvider` (unit-tested
    separately in test_phase41_data_acquisition.py), this lets a test
    dictate exactly ready/collected/failed per call without needing real
    files on disk."""

    def __init__(self, result: AcquisitionResult, *, data_dir: Path):
        self._result = result
        self.calls: list[str] = []
        self.data_dir = data_dir

    def acquire(self, symbols, slot_id):
        self.calls.append(slot_id)
        return self._result


def _running_experiment(tmp_path, *, universe=("AAPL",), now=NOW, minimum_days=14):
    monkeypatch_cwd = tmp_path
    config = build_experiment_config(now=now, universe=universe, starting_capital_usd=1000.0, minimum_days=minimum_days)
    paths = experiment_paths(config.experiment_id, base_dir=tmp_path / "paper_experiments")
    ExperimentConfigStore(paths.experiment_config_file).approve(config)
    state_store = ExperimentStateStore(paths.experiment_state_file)
    state_store.transition(experiment_id=config.experiment_id, to_status=ExperimentStatus.CREATED, at=now, reason="test")
    state_store.transition(experiment_id=config.experiment_id, to_status=ExperimentStatus.RUNNING, at=now, reason="test")
    return config, paths


def _sched_config(tmp_path, experiment_id, **overrides):
    return SchedulerConfig(
        experiment_id=experiment_id, cadence_minutes=15, data_acquisition_timeout_seconds=1,
        poll_interval_seconds=0.01, inbox_root=tmp_path / "inbox", **overrides,
    )


@pytest.fixture(autouse=True)
def _experiment_paths_use_tmp(monkeypatch, tmp_path):
    """`experiment_paths()` (used internally by cycle_runner/scheduler)
    defaults to the RELATIVE `logs/paper_experiments` -- patch its default
    base_dir so every test in this file is fully isolated from the real
    repo's logs/ directory AND from each other, matching
    test_phase40_engine.py's own `_paths(tmp_path, ...)` pattern applied
    at the module level instead of per-call."""
    import src.paper_trading.cycle_runner as cycle_runner_mod
    import src.paper_trading.engine as engine_mod
    import src.paper_trading.scheduler as scheduler_mod

    real_experiment_paths = engine_mod.experiment_paths

    def patched(experiment_id, base_dir=tmp_path / "paper_experiments"):
        return real_experiment_paths(experiment_id, base_dir=base_dir)

    monkeypatch.setattr(engine_mod, "experiment_paths", patched)
    monkeypatch.setattr(cycle_runner_mod, "experiment_paths", patched)
    monkeypatch.setattr(scheduler_mod, "experiment_paths", patched)
    return tmp_path


def _patch_market(monkeypatch, market, client=None):
    import src.paper_trading.cycle_runner as cycle_runner_mod

    monkeypatch.setattr(cycle_runner_mod, "load_static_hood_client_from_dir", lambda data_dir, account_number: (client or FakeClient()))
    monkeypatch.setattr(cycle_runner_mod, "HoodMarketDataProvider", lambda client, settings: market)


# --- market-open transition (item 5) -----------------------------------------------------------


def test_before_market_open_ticks_waiting_and_never_attempts_acquisition(tmp_path, monkeypatch, paper_settings):
    config, paths = _running_experiment(tmp_path)
    _patch_market(monkeypatch, _empty_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)
    event_store = build_event_store(sched_config)
    provider = FakeAcquisitionProvider(AcquisitionResult(ready=True, data_dir=tmp_path, collected_symbols=("AAPL",), failed_symbols=()), data_dir=tmp_path)

    premarket = NOW.replace(hour=13, minute=0)  # 9:00am ET
    outcome = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=premarket, base_settings=paper_settings)
    assert outcome == "MARKET_CLOSED"
    assert provider.calls == []
    events = [e.event for e in event_store.load_all()]
    assert events == [WAITING_FOR_MARKET_OPEN]


def test_at_market_open_the_tick_logs_market_open_and_proceeds(tmp_path, monkeypatch, paper_settings):
    config, paths = _running_experiment(tmp_path)
    _patch_market(monkeypatch, _empty_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)
    event_store = build_event_store(sched_config)
    provider = FakeAcquisitionProvider(AcquisitionResult(ready=True, data_dir=tmp_path, collected_symbols=("AAPL",), failed_symbols=()), data_dir=tmp_path)

    outcome = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)
    events = [e.event for e in event_store.load_all()]
    assert MARKET_OPEN in events
    assert DATA_COLLECTION_STARTED in events
    assert provider.calls == [slot_id_for(NOW, paper_settings, 15)]


# --- no fabricated data on acquisition failure (item 19) ---------------------------------------


def test_acquisition_failure_never_starts_a_cycle_and_never_touches_account_state(tmp_path, monkeypatch, paper_settings):
    config, paths = _running_experiment(tmp_path)
    _patch_market(monkeypatch, _bullish_market())  # even with a real bullish setup ready...
    sched_config = _sched_config(tmp_path, config.experiment_id)
    event_store = build_event_store(sched_config)
    provider = FakeAcquisitionProvider(
        AcquisitionResult(ready=False, data_dir=tmp_path, collected_symbols=(), failed_symbols=("AAPL",), reason="timed out"),
        data_dir=tmp_path,
    )

    outcome = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)
    assert outcome == "DATA_COLLECTION_FAILED"
    events = [e.event for e in event_store.load_all()]
    assert PAPER_CYCLE_STARTED not in events
    assert PAPER_ENTRY not in events
    assert DATA_COLLECTION_FAILED in events
    # ...and no account files were ever created -- no trade, no equity snapshot, fabricated from nothing.
    assert not paths.equity_curve_file.is_file()
    assert not paths.experiment_trades_file.is_file()


# --- partial / all-symbol data failure (items 9, 10) --------------------------------------------


def test_partial_symbol_failure_still_runs_the_cycle_and_logs_the_gap(tmp_path, monkeypatch, paper_settings):
    config, paths = _running_experiment(tmp_path, universe=("AAPL", "MSFT"))
    _patch_market(monkeypatch, _empty_market())  # no candidates anywhere -> NO_QUALIFIED_OPPORTUNITY, not a forced trade
    sched_config = _sched_config(tmp_path, config.experiment_id)
    event_store = build_event_store(sched_config)
    provider = FakeAcquisitionProvider(
        AcquisitionResult(ready=True, data_dir=tmp_path, collected_symbols=("AAPL",), failed_symbols=("MSFT",)), data_dir=tmp_path,
    )

    outcome = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)
    assert outcome == "NO_QUALIFIED_OPPORTUNITY"
    events = event_store.load_all()
    partial = next(e for e in events if e.event == DATA_COLLECTION_PARTIAL)
    assert partial.symbols_collected == 1 and partial.symbols_failed == 1
    assert any(e.event == PAPER_CYCLE_STARTED for e in events)


def test_all_symbol_failure_never_runs_a_cycle(tmp_path, monkeypatch, paper_settings):
    config, paths = _running_experiment(tmp_path, universe=("AAPL", "MSFT"))
    _patch_market(monkeypatch, _bullish_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)
    event_store = build_event_store(sched_config)
    provider = FakeAcquisitionProvider(
        AcquisitionResult(ready=True, data_dir=tmp_path, collected_symbols=(), failed_symbols=("AAPL", "MSFT")), data_dir=tmp_path,
    )
    outcome = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)
    assert outcome == "DATA_COLLECTION_FAILED"
    events = [e.event for e in event_store.load_all()]
    assert PAPER_CYCLE_STARTED not in events


# --- missing option quotes / no candidates never forces a trade (item 11) -----------------------


def test_no_option_data_anywhere_yields_no_qualified_opportunity_not_a_forced_trade(tmp_path, monkeypatch, paper_settings):
    config, paths = _running_experiment(tmp_path)
    _patch_market(monkeypatch, _empty_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)
    event_store = build_event_store(sched_config)
    provider = FakeAcquisitionProvider(AcquisitionResult(ready=True, data_dir=tmp_path, collected_symbols=("AAPL",), failed_symbols=()), data_dir=tmp_path)

    outcome = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)
    assert outcome == "NO_QUALIFIED_OPPORTUNITY"
    events = event_store.load_all()
    assert PAPER_ENTRY not in [e.event for e in events]
    result_event = next(e for e in events if e.event == NO_QUALIFIED_OPPORTUNITY)
    assert result_event.equity_usd == 1000.0
    assert result_event.open_positions == 0


# --- malformed Robinhood response (item 12) ------------------------------------------------------


def test_malformed_json_response_fails_the_cycle_without_crashing_the_scheduler(tmp_path, paper_settings):
    """This test deliberately does NOT monkeypatch the client loader --
    the REAL `load_static_hood_client_from_dir` reads real (here,
    deliberately corrupted) files off disk, exactly as it does in
    production."""
    config, paths = _running_experiment(tmp_path)
    sched_config = _sched_config(tmp_path, config.experiment_id)
    event_store = build_event_store(sched_config)

    slot_id = slot_id_for(NOW, paper_settings, sched_config.cadence_minutes)
    slot_dir = sched_config.resolved_inbox_root() / slot_id
    slot_dir.mkdir(parents=True)
    (slot_dir / "equity_quotes_AAPL.json").write_text("{not valid json at all")
    mark_inbox_slot_ready(sched_config.resolved_inbox_root(), slot_id)

    from src.paper_trading.data_acquisition import InboxDataAcquisitionProvider

    provider = InboxDataAcquisitionProvider(inbox_root=sched_config.resolved_inbox_root(), timeout_seconds=1, poll_interval_seconds=0.01)

    outcome = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)
    assert outcome == "PAPER_CYCLE_FAILED"
    events = [e.event for e in event_store.load_all()]
    assert PAPER_CYCLE_FAILED in events
    assert PAPER_ENTRY not in events
    # No account state was corrupted -- no equity snapshot was ever written for this failed attempt.
    assert not paths.equity_curve_file.is_file()


# --- duplicate-cycle prevention / restart behavior (items 7, 8) ---------------------------------


def test_a_second_tick_in_the_same_slot_is_deduplicated(tmp_path, monkeypatch, paper_settings):
    config, paths = _running_experiment(tmp_path)
    _patch_market(monkeypatch, _empty_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)
    event_store = build_event_store(sched_config)
    provider = FakeAcquisitionProvider(AcquisitionResult(ready=True, data_dir=tmp_path, collected_symbols=("AAPL",), failed_symbols=()), data_dir=tmp_path)

    first = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)
    second = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)
    assert first == "NO_QUALIFIED_OPPORTUNITY"
    assert second == "SLOT_ALREADY_COMPLETED"
    events = event_store.load_all()
    assert len([e for e in events if e.event == PAPER_CYCLE_STARTED]) == 1  # never re-ran
    assert provider.calls == [slot_id_for(NOW, paper_settings, 15)]  # acquisition was never attempted a second time either


def test_restarting_with_a_brand_new_event_store_still_sees_the_completed_slot(tmp_path, monkeypatch, paper_settings):
    """Restart behavior (item 7): a fresh `SchedulerEventStore` instance
    over the SAME path replays the same history -- the exact durability
    guarantee `ExperimentStateStore`/`CycleLogStore` already rely on."""
    config, paths = _running_experiment(tmp_path)
    _patch_market(monkeypatch, _empty_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)
    event_store = build_event_store(sched_config)
    provider = FakeAcquisitionProvider(AcquisitionResult(ready=True, data_dir=tmp_path, collected_symbols=("AAPL",), failed_symbols=()), data_dir=tmp_path)
    run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)

    fresh_event_store = build_event_store(sched_config)  # simulates a brand-new process
    slot = slot_id_for(NOW, paper_settings, 15)
    assert slot in fresh_event_store.completed_slot_ids()

    second = run_scheduler_tick(config=sched_config, event_store=fresh_event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)
    assert second == "SLOT_ALREADY_COMPLETED"


def test_a_restart_five_minutes_later_in_the_same_slot_does_not_duplicate(tmp_path, monkeypatch, paper_settings):
    config, paths = _running_experiment(tmp_path)
    _patch_market(monkeypatch, _empty_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)
    event_store = build_event_store(sched_config)
    provider = FakeAcquisitionProvider(AcquisitionResult(ready=True, data_dir=tmp_path, collected_symbols=("AAPL",), failed_symbols=()), data_dir=tmp_path)

    run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)
    restart_at_935 = NOW + timedelta(minutes=5)
    outcome = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=restart_at_935, base_settings=paper_settings)
    assert outcome == "SLOT_ALREADY_COMPLETED"


# --- repeated intraday cycles / open-position exit evaluation (items 20, 21) ---------------------


def test_a_new_slot_the_next_cadence_interval_runs_a_second_cycle(tmp_path, monkeypatch, paper_settings):
    """Item 21: the scheduler is not limited to one market-open cycle a
    day -- a later intraday slot runs its own independent cycle."""
    config, paths = _running_experiment(tmp_path)
    _patch_market(monkeypatch, _empty_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)
    event_store = build_event_store(sched_config)
    provider = FakeAcquisitionProvider(AcquisitionResult(ready=True, data_dir=tmp_path, collected_symbols=("AAPL",), failed_symbols=()), data_dir=tmp_path)

    first = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)
    later = NOW + timedelta(minutes=16)  # past the 15-minute cadence -> a new slot
    second = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=later, base_settings=paper_settings)
    assert first == "NO_QUALIFIED_OPPORTUNITY"
    assert second == "NO_QUALIFIED_OPPORTUNITY"
    assert len([e for e in event_store.load_all() if e.event == PAPER_CYCLE_STARTED]) == 2
    assert provider.calls == [slot_id_for(NOW, paper_settings, 15), slot_id_for(later, paper_settings, 15)]


def test_an_open_position_is_still_tracked_and_re_evaluated_on_the_next_intraday_slot(tmp_path, monkeypatch, paper_settings):
    """Item 20: a real entry opened on slot 1 is still open (not
    duplicated, not dropped) when slot 2's cycle runs -- proving the
    SAME already-open-position machinery (`RiskManager`/
    `PositionEvaluator`, unmodified) is invoked again by the scheduler,
    not bypassed. Exit MECHANICS themselves are Phase 36/orchestrator's
    job, already tested unmodified in test_orchestrator.py; this test
    only proves the scheduler keeps driving subsequent cycles against an
    already-open position rather than only ever handling entries."""
    config, paths = _running_experiment(tmp_path)
    _patch_market(monkeypatch, _bullish_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)
    event_store = build_event_store(sched_config)
    provider = FakeAcquisitionProvider(AcquisitionResult(ready=True, data_dir=tmp_path, collected_symbols=("AAPL",), failed_symbols=()), data_dir=tmp_path)

    first = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)
    assert first == "CYCLE_OK"
    assert any(e.event == PAPER_ENTRY for e in event_store.load_all())

    from src.position_manager.store import PaperPositionStore

    assert len(PaperPositionStore(paths.paper_positions_file).load()) == 1

    later = NOW + timedelta(minutes=16)
    second = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=later, base_settings=paper_settings)
    # RiskManager's own "no duplicate position in this contract" check
    # (unmodified, reused) blocks a second entry -- the position from
    # slot 1 was re-evaluated, not silently ignored or duplicated.
    assert second in ("NO_QUALIFIED_OPPORTUNITY", "CYCLE_OK")
    assert len(PaperPositionStore(paths.paper_positions_file).load()) == 1


# --- process restart while a position exists (item 22) -------------------------------------------


def test_process_restart_with_an_open_position_reloads_it_from_disk(tmp_path, monkeypatch, paper_settings):
    config, paths = _running_experiment(tmp_path)
    _patch_market(monkeypatch, _bullish_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)
    event_store = build_event_store(sched_config)
    provider = FakeAcquisitionProvider(AcquisitionResult(ready=True, data_dir=tmp_path, collected_symbols=("AAPL",), failed_symbols=()), data_dir=tmp_path)
    run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)

    # Simulate a full process restart: brand-new store instances over the SAME paths.
    from src.paper_trading.equity_curve import EquitySnapshotStore
    from src.paper_trading.journal import PaperExperimentTradeStore
    from src.position_manager.store import PaperPositionStore

    fresh_positions = PaperPositionStore(paths.paper_positions_file)
    fresh_trades = PaperExperimentTradeStore(paths.experiment_trades_file)
    fresh_equity = EquitySnapshotStore(paths.equity_curve_file)
    fresh_events = build_event_store(sched_config)

    assert len(fresh_positions.load()) == 1
    assert len(fresh_trades.load_all()) == 1
    assert fresh_equity.latest() is not None
    assert fresh_events.last_successful_cycle() is not None

    # The restarted scheduler continues correctly: the same slot is
    # recognized as already completed, and a later slot still evaluates
    # the reloaded open position without duplicating it.
    later = NOW + timedelta(minutes=16)
    outcome = run_scheduler_tick(config=sched_config, event_store=fresh_events, acquisition_provider=provider, now=later, base_settings=paper_settings)
    assert outcome in ("NO_QUALIFIED_OPPORTUNITY", "CYCLE_OK")
    assert len(fresh_positions.load()) == 1


# --- experiment end-date enforcement (item 16) ----------------------------------------------------


def test_experiment_completed_status_stops_the_scheduler_from_running_further_cycles(tmp_path, monkeypatch, paper_settings):
    config, paths = _running_experiment(tmp_path, minimum_days=14)
    _patch_market(monkeypatch, _empty_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)
    event_store = build_event_store(sched_config)
    provider = FakeAcquisitionProvider(AcquisitionResult(ready=True, data_dir=tmp_path, collected_symbols=("AAPL",), failed_symbols=()), data_dir=tmp_path)

    # Force COMPLETED directly (as the real duration-based auto-complete would).
    state_store = ExperimentStateStore(paths.experiment_state_file)
    state_store.transition(experiment_id=config.experiment_id, to_status=ExperimentStatus.COMPLETED, at=NOW, reason="test: reached minimum duration")

    outcome = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW + timedelta(days=1), base_settings=paper_settings)
    assert outcome == "EXPERIMENT_TERMINAL"
    assert provider.calls == []  # never even attempted acquisition for a terminal experiment
    events = [e.event for e in event_store.load_all()]
    assert events == [EXPERIMENT_COMPLETED]


def test_auto_complete_after_reaching_minimum_duration_then_stops_future_ticks(tmp_path, monkeypatch, paper_settings):
    """End-to-end: the SAME duration-based auto-complete
    `scripts/paper_experiment.py::cmd_run_cycle` already performs (now
    shared via `src.paper_trading.cycle_runner`) fires through the
    scheduler too, and the NEXT tick then refuses to run a cycle."""
    config, paths = _running_experiment(tmp_path, now=NOW, minimum_days=14)
    _patch_market(monkeypatch, _empty_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)
    event_store = build_event_store(sched_config)
    provider = FakeAcquisitionProvider(AcquisitionResult(ready=True, data_dir=tmp_path, collected_symbols=("AAPL",), failed_symbols=()), data_dir=tmp_path)

    far_future = NOW + timedelta(days=15)  # past the 14-calendar-day minimum
    outcome = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=far_future, base_settings=paper_settings)
    assert outcome == "NO_QUALIFIED_OPPORTUNITY"
    assert any(e.event == EXPERIMENT_COMPLETED for e in event_store.load_all())

    next_day = far_future + timedelta(days=1)
    next_outcome = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=next_day, base_settings=paper_settings)
    assert next_outcome == "EXPERIMENT_TERMINAL"


# --- run_scheduler_forever: the real-time loop wrapper (item 21 continued) -----------------------


def test_run_scheduler_forever_advances_through_several_slots_then_stops_on_completion(tmp_path, monkeypatch, paper_settings):
    config, paths = _running_experiment(tmp_path, now=NOW, minimum_days=14)
    _patch_market(monkeypatch, _empty_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)

    clock = {"now": NOW}

    def now_fn():
        current = clock["now"]
        clock["now"] = current + timedelta(minutes=16)  # advance one full slot per tick
        return current

    # Monkeypatch acquisition at the module level used inside run_scheduler_forever.
    import src.paper_trading.scheduler as scheduler_mod

    fake_provider = FakeAcquisitionProvider(AcquisitionResult(ready=True, data_dir=tmp_path, collected_symbols=("AAPL",), failed_symbols=()), data_dir=tmp_path)
    monkeypatch.setattr(scheduler_mod, "build_acquisition_provider", lambda cfg, sleep_fn=None: fake_provider)

    run_scheduler_forever(sched_config, sleep_fn=lambda s: None, now_fn=now_fn, max_iterations=3, base_settings=paper_settings)

    event_store = build_event_store(sched_config)
    events = [e.event for e in event_store.load_all()]
    assert events[0] == PAPER_SCHEDULER_STARTED
    assert events[-1] == PAPER_SCHEDULER_STOPPED
    assert len([e for e in events if e == PAPER_CYCLE_STARTED]) == 3  # three distinct slots, three real cycles
    assert len(fake_provider.calls) == 3
    assert len(set(fake_provider.calls)) == 3  # three DISTINCT slot ids -- never re-polled the same slot
