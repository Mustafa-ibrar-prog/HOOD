"""Phase 38, Part 10-12 — economic validation, $1,000 affordability, and
live-observation replication."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.options.phase38_affordability import evaluate_thousand_dollar_affordability
from src.options.phase38_economic_validation import build_economic_validation_report
from src.options.phase38_live_replication import evaluate_live_replication
from src.options.phase38_targets import ForwardOutcome
from src.research_recorder.recorder import RecorderStores, run_observation_cycle
from src.research_recorder.storage import CycleLogStore, NormalizedOptionStore, NormalizedUnderlyingStore, RawObservationStore, ResearchSignalStore


def _outcome(ret, entry_ask=1.0, entry_bid=0.95, t=None, holding_minutes=5):
    t = t or datetime(2026, 9, 1, tzinfo=timezone.utc)
    exit_ask = entry_ask * (1 + ret) + 0.02
    exit_bid = entry_ask * (1 + ret)
    return ForwardOutcome(
        option_id="opt-1", underlying_symbol="AAPL", horizon_label="5min", entry_cycle_id="c0", entry_timestamp=t,
        exit_cycle_id="c1", exit_timestamp=t + timedelta(minutes=holding_minutes), entry_ask=entry_ask, entry_bid=entry_bid,
        exit_bid=exit_bid, exit_ask=exit_ask, mid_return_pct=ret, executable_return_pct=ret, mfe_pct=max(ret, 0),
        mae_pct=min(ret, 0), directional_outcome="UP" if ret > 0 else "DOWN", risk_adjusted_outcome=None,
        entry_underlying=100.0, exit_underlying=100.0, underlying_return_pct=0.0, option_minus_underlying_return_pct=ret,
        data_limited_reason=None,
    )


# --- Economic validation ------------------------------------------------------------------------


def test_economic_report_empty():
    report = build_economic_validation_report([])
    assert report.n_trades == 0 and report.expectancy is None


def test_economic_report_basic_stats():
    outcomes = [_outcome(0.5), _outcome(-0.3), _outcome(0.2), _outcome(-0.1)]
    report = build_economic_validation_report(outcomes)
    assert report.n_trades == 4
    assert report.win_rate == 0.5
    assert report.profit_factor is not None
    assert report.payoff_ratio is not None


def test_economic_report_drawdown_reflects_a_losing_streak():
    outcomes = [_outcome(-0.2), _outcome(-0.2), _outcome(-0.2)]
    report = build_economic_validation_report(outcomes)
    assert report.max_drawdown_pct > 0.4  # compounded losses


def test_economic_report_sortino_none_with_no_downside():
    outcomes = [_outcome(0.1), _outcome(0.2), _outcome(0.3)]
    report = build_economic_validation_report(outcomes)
    assert report.sortino_like is None  # no downside deviation to compute


def test_economic_report_holding_period_and_turnover():
    outcomes = [_outcome(0.1, t=datetime(2026, 9, 1, tzinfo=timezone.utc), holding_minutes=30), _outcome(0.1, t=datetime(2026, 9, 3, tzinfo=timezone.utc), holding_minutes=60)]
    report = build_economic_validation_report(outcomes)
    assert report.average_holding_period_minutes == 45.0
    assert report.turnover_trades_per_day is not None


# --- Affordability ---------------------------------------------------------------------------


def test_affordability_empty():
    result = evaluate_thousand_dollar_affordability([])
    assert result.classification == "ACCOUNT_FEASIBILITY_UNKNOWN_NO_PRICED_ROWS"
    assert result.max_simultaneous_positions_at_equity is None


def test_affordability_computes_max_simultaneous_positions():
    outcomes = [_outcome(0.1, entry_ask=2.00)] * 10  # $200/contract premium
    result = evaluate_thousand_dollar_affordability(outcomes, account_equity_usd=1000.0)
    assert result.max_simultaneous_positions_at_equity == 5  # 1000 // 200
    assert result.max_loss_single_position_usd == 200.0
    assert result.max_loss_all_simultaneous_positions_usd == 1000.0


def test_affordability_flags_expensive_contracts_clearly():
    outcomes = [_outcome(0.1, entry_ask=35.0)] * 10  # $3,500/contract -- Part 11's explicit example
    result = evaluate_thousand_dollar_affordability(outcomes, account_equity_usd=1000.0)
    assert result.max_simultaneous_positions_at_equity == 0
    assert result.report.pct_affordable_with_account == 0.0


def test_affordability_never_imposes_a_fixed_daily_return_requirement():
    """Structural check: nothing in this module's fields references a
    percentage-per-day requirement."""
    import dataclasses

    from src.options.phase38_affordability import ThousandDollarAffordabilityResult

    field_names = {f.name for f in dataclasses.fields(ThousandDollarAffordabilityResult)}
    assert not any("daily_return" in n or "pct_per_day" in n for n in field_names)


# --- Live replication -------------------------------------------------------------------------


def _stores(tmp_path):
    return RecorderStores(
        raw=RawObservationStore(tmp_path / "raw.jsonl"), underlying=NormalizedUnderlyingStore(tmp_path / "u.jsonl"),
        option=NormalizedOptionStore(tmp_path / "o.jsonl"), signal=ResearchSignalStore(tmp_path / "s.jsonl"),
        cycle_log=CycleLogStore(tmp_path / "c.jsonl"),
    )


def test_live_replication_reports_zero_cycles_honestly():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        report = evaluate_live_replication(stores=stores, dataset=[])
        assert report.n_cycles_available == 0
        assert not report.sufficient_for_replication
        assert "Zero observation cycles" in report.reason


def test_live_replication_never_computes_a_pnl_field():
    import dataclasses

    from src.options.phase38_live_replication import LiveReplicationReport

    field_names = {f.name for f in dataclasses.fields(LiveReplicationReport)}
    for forbidden in ("pnl", "profit", "loss", "balance"):
        assert not any(forbidden in n for n in field_names), field_names


def test_live_replication_with_a_real_recorded_cycle():
    from src.config.settings import Settings
    from src.market.data_provider import MarketDataProvider
    from src.options.phase38_causal_validation_dataset import build_causal_validation_dataset

    NOW = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)

    class FakeClient:
        def get_equity_quotes(self, symbols):
            return {"data": {"results": [{"quote": {"symbol": symbols[0], "bid_price": None, "ask_price": None, "last_trade_price": "230.0", "venue_last_trade_time": NOW.isoformat()}, "close": {"price": "228.0"}}]}}

        def get_option_quotes(self, instrument_ids):
            return {"data": {"results": [{"quote": {"instrument_id": oid, "bid_price": "1.0", "ask_price": "1.05", "updated_at": NOW.isoformat()}} for oid in instrument_ids]}}

    class FakeMarket(MarketDataProvider):
        def get_market_snapshot(self, option_id, underlying_symbol, now=None): raise NotImplementedError
        def get_underlying_snapshot(self, symbol, now=None): raise NotImplementedError
        def get_option_expirations(self, underlying_symbol): return [NOW.date() + timedelta(days=30)]
        def get_option_chain_candidates(self, underlying_symbol, **filters):
            return [{"id": "opt-AAPL-230", "type": "call", "strike_price": "230.0", "expiration_date": (NOW.date() + timedelta(days=30)).isoformat(), "state": "active", "tradability": "tradable"}]

    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        stores = _stores(p)
        run_observation_cycle(client=FakeClient(), market=FakeMarket(), settings=Settings.from_env(env={"TRADING_MODE": "paper"}), stores=stores, now=NOW, universe=["AAPL"])
        dataset = build_causal_validation_dataset(raw_store=stores.raw, underlying_store=stores.underlying, option_store=stores.option)
        report = evaluate_live_replication(stores=stores, dataset=dataset)
        assert report.n_cycles_available == 1
        assert report.feature_availability_pct["option_bid"] == 1.0
        assert not report.sufficient_for_replication  # 1 cycle < 20
