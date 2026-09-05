"""Phase 35, Parts E-H — the campaign orchestrator, end-to-end on a
small SYNTHETIC store (fast, deterministic). Established Phase 30
discipline: this fixture exercises code mechanics only, never presented
as real research evidence -- the real numbers come from the real-data
campaign run (scripts/phase35_run_backtest_campaign.py)."""

from __future__ import annotations

from datetime import date

from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.phase35_backtest_campaign import (
    USABLE_UNDERLYINGS,
    affordability_for_trades,
    build_campaign_data,
    cost_stress_sweep,
    run_baseline_backtest,
)
from tests.phase30_fixtures import synthetic_daily_multi_bar_store


def _combined_store(n_bars: int = 30, expiration=date(2026, 9, 10)) -> InMemoryLeanSampleStore:
    """A single AAPL contract with `n_bars` real daily observations, an
    uptrending underlying price (real breakout-signal-triggering shape,
    mirroring test_phase35_underlying_signal.py's own synthetic uptrend),
    expiration chosen so DTE crosses into MOMENTUM_BREAKOUT_EXISTING_V1's
    [7, 45] window partway through the series."""
    return synthetic_daily_multi_bar_store(n_bars=n_bars, strike=190.0, expiration=expiration, underlying="AAPL")


def test_build_campaign_data_runs_end_to_end_without_crashing():
    store = _combined_store()
    data = build_campaign_data(store)
    assert isinstance(data.contract_day_rows, list)
    assert set(data.signals_by_underlying) == set(USABLE_UNDERLYINGS)
    # matched/unmatched together account for every real signal detected
    total_signals = sum(len(v) for v in data.signals_by_underlying.values())
    assert len(data.matched_trades) + len(data.unmatched_signals) == total_signals


def test_run_baseline_backtest_never_crashes_on_zero_or_few_trades():
    store = _combined_store()
    data = build_campaign_data(store)
    result = run_baseline_backtest(data)
    assert result.metrics is not None
    assert result.starting_cash == 1_000_000.0


def test_affordability_for_trades_handles_empty_trade_list():
    report, classification = affordability_for_trades(())
    assert classification == "ACCOUNT_FEASIBILITY_UNKNOWN_NO_PRICED_ROWS"


def test_cost_stress_sweep_handles_no_matched_trades_gracefully():
    store = synthetic_daily_multi_bar_store(n_bars=5, underlying="AAPL")  # too short for any real signal
    data = build_campaign_data(store)
    result = cost_stress_sweep(data)
    assert result is None or result.points  # either genuinely no data, or a real sweep result


def test_only_usable_underlyings_get_signal_detection():
    store = _combined_store()
    data = build_campaign_data(store)
    assert set(data.underlying_daily_series) == set(USABLE_UNDERLYINGS)
    # FOXA/NWSA/TWX are never even attempted -- frozen exclusion, not a runtime filter on empty results
    assert "FOXA" not in data.underlying_daily_series
    assert "TWX" not in data.underlying_daily_series
