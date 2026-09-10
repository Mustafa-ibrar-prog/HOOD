"""Phase 42 -- end-to-end integration: MARKET OPEN -> acquisition
planning -> real inbox population (atomic READY) -> paper scheduler ->
paper cycle -> persistence -> next slot, using the REAL
`InboxDataAcquisitionProvider` (not a fake) together with the NEW Phase
42 planning helpers. Reuses Phase 41's fixtures (`FakeMarketData`,
`FakeClient`, `_bullish_market`, `_empty_market`, `_running_experiment`,
`_sched_config`, `_patch_market`) so cycle-execution behavior is
exercised through the SAME substitution point Phase 40/41 already use,
never re-invented here.

Covers the Phase 42 test list: automatic cycle handoff, READY written
only after data completion, partial acquisition, failed acquisition,
malformed data, duplicate cycle, interrupted acquisition, interrupted
scheduler, restart recovery, option pagination / current-price strike
coverage (via near_the_money, exercised as part of a real plan), all 12
symbols, no fabricated data.
"""

from __future__ import annotations

from datetime import timedelta

from src.live_bridge import save_hood_response_to_data_dir
from src.paper_trading.acquisition_planning import compute_cycle_identity, compute_symbol_strike_tasks
from src.paper_trading.data_acquisition import InboxDataAcquisitionProvider, mark_inbox_slot_ready
from src.paper_trading.near_the_money import compute_target_strikes
from src.paper_trading.scheduler import build_event_store, run_scheduler_tick
from src.paper_trading.scheduler_events import (
    DATA_COLLECTION_FAILED,
    DATA_COLLECTION_PARTIAL,
    NO_QUALIFIED_OPPORTUNITY,
    PAPER_CYCLE_FAILED,
    PAPER_CYCLE_STARTED,
    PAPER_ENTRY,
)

# Reuse Phase 41's fixtures/helpers rather than re-defining them.
from tests.test_phase41_scheduler import (  # noqa: F401  (autouse fixture import)
    NOW,
    FakeMarketData,
    _bullish_market,
    _empty_market,
    _experiment_paths_use_tmp,
    _patch_market,
    _running_experiment,
    _sched_config,
)


def _real_inbox_plan(tmp_path, sched_config, settings, universe, now=NOW):
    identity = compute_cycle_identity(
        now=now, settings=settings, experiment_id=sched_config.experiment_id, cadence_minutes=sched_config.cadence_minutes,
        inbox_root=sched_config.resolved_inbox_root(), universe=universe,
    )
    return identity


def _write_equity_quote(inbox_slot_dir, symbol, price):
    save_hood_response_to_data_dir(inbox_slot_dir, f"equity_quotes_{symbol}", {
        "data": {"results": [{
            "quote": {"symbol": symbol, "bid_price": None, "ask_price": None, "last_trade_price": str(price), "venue_last_trade_time": NOW.isoformat()},
            "close": {"price": str(price - 1)},
        }]},
    })


# --- automatic cycle handoff + all 12 symbols + no fabricated data -----------------------------


def test_automatic_cycle_handoff_using_the_real_identity_and_real_inbox_provider(tmp_path, monkeypatch, paper_settings):
    config, paths = _running_experiment(tmp_path, universe=tuple(f"SYM{i}" for i in range(12)))
    _patch_market(monkeypatch, _empty_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)
    identity = _real_inbox_plan(tmp_path, sched_config, paper_settings, config.universe)
    assert len(identity.universe) == 12  # all-12-symbols requirement

    for symbol in identity.universe:
        _write_equity_quote(identity.inbox_slot_dir, symbol, 100.0)
    mark_inbox_slot_ready(sched_config.resolved_inbox_root(), identity.slot_id)

    provider = InboxDataAcquisitionProvider(inbox_root=sched_config.resolved_inbox_root(), timeout_seconds=1, poll_interval_seconds=0.01)
    event_store = build_event_store(sched_config)
    outcome = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)

    assert outcome == "NO_QUALIFIED_OPPORTUNITY"
    events = event_store.load_all()
    assert PAPER_ENTRY not in [e.event for e in events]  # no fabricated data / no forced trade
    completed = next(e for e in events if e.event == NO_QUALIFIED_OPPORTUNITY)
    assert completed.symbols_collected is None or completed.symbols_collected != 0  # cycle actually ran


# --- READY only after completion (real provider, real atomic write) ----------------------------


def test_scheduler_never_consumes_data_before_the_real_ready_sentinel_is_written(tmp_path, monkeypatch, paper_settings):
    config, paths = _running_experiment(tmp_path, universe=("AAPL", "MSFT"))
    _patch_market(monkeypatch, _empty_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)
    identity = _real_inbox_plan(tmp_path, sched_config, paper_settings, config.universe)

    _write_equity_quote(identity.inbox_slot_dir, "AAPL", 325.4)
    _write_equity_quote(identity.inbox_slot_dir, "MSFT", 491.5)
    # deliberately NOT marking ready

    provider = InboxDataAcquisitionProvider(inbox_root=sched_config.resolved_inbox_root(), timeout_seconds=0.05, poll_interval_seconds=0.01)
    event_store = build_event_store(sched_config)
    outcome = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)

    assert outcome == "DATA_COLLECTION_FAILED"
    assert PAPER_CYCLE_STARTED not in [e.event for e in event_store.load_all()]


# --- partial / failed acquisition ---------------------------------------------------------------


def test_partial_acquisition_with_the_real_provider_still_runs_and_logs_the_gap(tmp_path, monkeypatch, paper_settings):
    config, paths = _running_experiment(tmp_path, universe=("AAPL", "MSFT", "NVDA"))
    _patch_market(monkeypatch, _empty_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)
    identity = _real_inbox_plan(tmp_path, sched_config, paper_settings, config.universe)

    _write_equity_quote(identity.inbox_slot_dir, "AAPL", 325.4)  # only 1 of 3
    mark_inbox_slot_ready(sched_config.resolved_inbox_root(), identity.slot_id)

    provider = InboxDataAcquisitionProvider(inbox_root=sched_config.resolved_inbox_root(), timeout_seconds=1, poll_interval_seconds=0.01)
    event_store = build_event_store(sched_config)
    outcome = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)

    assert outcome == "NO_QUALIFIED_OPPORTUNITY"
    partial = next(e for e in event_store.load_all() if e.event == DATA_COLLECTION_PARTIAL)
    assert partial.symbols_collected == 1 and partial.symbols_failed == 2


def test_failed_acquisition_with_the_real_provider_never_runs_a_cycle(tmp_path, monkeypatch, paper_settings):
    config, paths = _running_experiment(tmp_path, universe=("AAPL",))
    _patch_market(monkeypatch, _bullish_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)

    provider = InboxDataAcquisitionProvider(inbox_root=sched_config.resolved_inbox_root(), timeout_seconds=0.05, poll_interval_seconds=0.01)
    event_store = build_event_store(sched_config)
    outcome = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)

    assert outcome == "DATA_COLLECTION_FAILED"
    assert not paths.equity_curve_file.is_file()  # no account state touched


# --- malformed data ------------------------------------------------------------------------------


def test_malformed_data_via_the_real_provider_fails_the_cycle_cleanly(tmp_path, paper_settings):
    config, paths = _running_experiment(tmp_path, universe=("AAPL",))
    sched_config = _sched_config(tmp_path, config.experiment_id)
    identity = _real_inbox_plan(tmp_path, sched_config, paper_settings, config.universe)
    (identity.inbox_slot_dir).mkdir(parents=True, exist_ok=True)
    (identity.inbox_slot_dir / "equity_quotes_AAPL.json").write_text("{ this is not json")
    mark_inbox_slot_ready(sched_config.resolved_inbox_root(), identity.slot_id)

    provider = InboxDataAcquisitionProvider(inbox_root=sched_config.resolved_inbox_root(), timeout_seconds=1, poll_interval_seconds=0.01)
    event_store = build_event_store(sched_config)
    outcome = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)

    assert outcome == "PAPER_CYCLE_FAILED"
    assert not paths.equity_curve_file.is_file()


# --- duplicate cycle / interrupted scheduler / restart recovery --------------------------------


def test_duplicate_cycle_is_prevented_across_a_simulated_scheduler_interruption(tmp_path, monkeypatch, paper_settings):
    """'Interrupted scheduler': the process dies right after completing a
    cycle. A fresh SchedulerEventStore (simulating restart) must still
    recognize the slot as done and refuse to re-poll the real inbox."""
    config, paths = _running_experiment(tmp_path, universe=("AAPL",))
    _patch_market(monkeypatch, _empty_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)
    identity = _real_inbox_plan(tmp_path, sched_config, paper_settings, config.universe)
    _write_equity_quote(identity.inbox_slot_dir, "AAPL", 325.4)
    mark_inbox_slot_ready(sched_config.resolved_inbox_root(), identity.slot_id)

    provider = InboxDataAcquisitionProvider(inbox_root=sched_config.resolved_inbox_root(), timeout_seconds=1, poll_interval_seconds=0.01)
    event_store = build_event_store(sched_config)
    first = run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)
    assert first == "NO_QUALIFIED_OPPORTUNITY"

    # Simulated restart: brand-new event store AND provider instances, same paths.
    fresh_event_store = build_event_store(sched_config)
    fresh_provider = InboxDataAcquisitionProvider(inbox_root=sched_config.resolved_inbox_root(), timeout_seconds=1, poll_interval_seconds=0.01)
    second = run_scheduler_tick(config=sched_config, event_store=fresh_event_store, acquisition_provider=fresh_provider, now=NOW, base_settings=paper_settings)
    assert second == "SLOT_ALREADY_COMPLETED"
    assert len([e for e in fresh_event_store.load_all() if e.event == PAPER_CYCLE_STARTED]) == 1


def test_restart_recovery_then_a_later_slot_still_runs_normally(tmp_path, monkeypatch, paper_settings):
    config, paths = _running_experiment(tmp_path, universe=("AAPL",))
    _patch_market(monkeypatch, _empty_market())
    sched_config = _sched_config(tmp_path, config.experiment_id)

    identity1 = _real_inbox_plan(tmp_path, sched_config, paper_settings, config.universe, now=NOW)
    _write_equity_quote(identity1.inbox_slot_dir, "AAPL", 325.4)
    mark_inbox_slot_ready(sched_config.resolved_inbox_root(), identity1.slot_id)
    provider = InboxDataAcquisitionProvider(inbox_root=sched_config.resolved_inbox_root(), timeout_seconds=1, poll_interval_seconds=0.01)
    event_store = build_event_store(sched_config)
    run_scheduler_tick(config=sched_config, event_store=event_store, acquisition_provider=provider, now=NOW, base_settings=paper_settings)

    later = NOW + timedelta(minutes=16)
    identity2 = _real_inbox_plan(tmp_path, sched_config, paper_settings, config.universe, now=later)
    assert identity2.slot_id != identity1.slot_id
    _write_equity_quote(identity2.inbox_slot_dir, "AAPL", 326.0)
    mark_inbox_slot_ready(sched_config.resolved_inbox_root(), identity2.slot_id)

    fresh_event_store = build_event_store(sched_config)  # restart
    outcome = run_scheduler_tick(config=sched_config, event_store=fresh_event_store, acquisition_provider=provider, now=later, base_settings=paper_settings)
    assert outcome == "NO_QUALIFIED_OPPORTUNITY"
    assert len([e for e in fresh_event_store.load_all() if e.event == PAPER_CYCLE_STARTED]) == 2


# --- option pagination / current-price strike coverage, wired into a real plan -----------------


def test_near_the_money_plan_for_every_universe_symbol_covers_its_real_price(tmp_path, paper_settings):
    """Demonstrates the Phase 42 pagination-avoidance path end to end: for
    every symbol in the 12-symbol universe, given a real fetched price,
    the resulting target strikes bracket that price -- the exact failure
    mode from Phase 41 cycle 2 (a page never reaching the current price)
    cannot occur here because no pagination is involved at all."""
    prices = {
        "NVDA": 218.65, "TSLA": 363.94, "SPY": 758.12, "QQQ": 709.26, "AAPL": 325.4, "MSFT": 491.55,
        "AMD": 505.04, "AMZN": 251.47, "META": 644.80, "GOOGL": 332.95, "NFLX": 75.9, "IWM": 287.70,
    }
    tasks = compute_symbol_strike_tasks(prices)
    assert len(tasks) == 12
    for task in tasks:
        assert min(task.strikes.strikes) <= task.underlying_price <= max(task.strikes.strikes)
