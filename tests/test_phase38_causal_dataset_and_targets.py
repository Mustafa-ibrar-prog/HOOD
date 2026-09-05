"""Phase 38, Part 2-3/16 — the causal validation dataset layer, forward
targets, and anti-lookahead enforcement."""

from __future__ import annotations

import inspect
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.options.phase38_causal_validation_dataset import (
    CausalFeatureRow,
    build_causal_feature_row,
    build_causal_validation_dataset,
)
from src.options.phase38_targets import (
    DEFAULT_HORIZONS,
    ForwardHorizon,
    compute_forward_outcome,
    compute_forward_outcomes_all_horizons,
)
from src.research_recorder.recorder import RecorderStores
from src.research_recorder.storage import CycleLogStore, NormalizedOptionStore, NormalizedUnderlyingStore, RawObservationStore, ResearchSignalStore


def _row(t_minutes, bid, ask, *, option_id="opt-1", underlying=230.0, cycle="cyc"):
    return CausalFeatureRow(
        observation_cycle_id=f"{cycle}-{t_minutes}",
        observation_timestamp=datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc) + timedelta(minutes=t_minutes),
        underlying_symbol="AAPL", option_id=option_id, option_type="call", strike=230.0, expiration=None, dte=30,
        moneyness=0.0, underlying_last=underlying, underlying_bid=None, underlying_ask=None, underlying_midpoint=underlying,
        option_bid=bid, option_ask=ask, option_bid_size=5, option_ask_size=5,
        option_mark=(bid + ask) / 2 if bid is not None and ask is not None else None,
        option_midpoint=(bid + ask) / 2 if bid is not None and ask is not None else None,
        implied_volatility=0.3, delta=0.5, gamma=None, theta=None, vega=None, rho=None, open_interest=100, volume=50,
        contract_state="active", contract_tradability="tradable", field_provenance={}, raw_payload_fingerprint="fp",
    )


# --- Causal dataset construction ---------------------------------------------------------------


def test_build_causal_feature_row_is_a_pure_function_of_one_observation():
    """Structural anti-lookahead guarantee: the function signature has
    no parameter through which a later observation could be passed."""
    sig = inspect.signature(build_causal_feature_row)
    param_names = set(sig.parameters)
    assert param_names == {"option_row", "underlying_row", "raw_payload_fingerprint"}


def test_causal_dataset_empty_when_no_observations_recorded():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        stores = RecorderStores(
            raw=RawObservationStore(p / "raw.jsonl"), underlying=NormalizedUnderlyingStore(p / "u.jsonl"),
            option=NormalizedOptionStore(p / "o.jsonl"), signal=ResearchSignalStore(p / "s.jsonl"),
            cycle_log=CycleLogStore(p / "c.jsonl"),
        )
        dataset = build_causal_validation_dataset(raw_store=stores.raw, underlying_store=stores.underlying, option_store=stores.option)
        assert dataset == []


def test_causal_dataset_joins_underlying_and_option_rows_from_the_real_recorder():
    import src.research_recorder.recorder as recorder_module
    from src.config.settings import Settings
    from src.market.data_provider import MarketDataProvider

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
        stores = RecorderStores(
            raw=RawObservationStore(p / "raw.jsonl"), underlying=NormalizedUnderlyingStore(p / "u.jsonl"),
            option=NormalizedOptionStore(p / "o.jsonl"), signal=ResearchSignalStore(p / "s.jsonl"),
            cycle_log=CycleLogStore(p / "c.jsonl"),
        )
        recorder_module.run_observation_cycle(client=FakeClient(), market=FakeMarket(), settings=Settings.from_env(env={"TRADING_MODE": "paper"}), stores=stores, now=NOW, universe=["AAPL"])
        dataset = build_causal_validation_dataset(raw_store=stores.raw, underlying_store=stores.underlying, option_store=stores.option)
        assert len(dataset) == 1
        assert dataset[0].underlying_last == 230.0
        assert dataset[0].option_bid == 1.0
        assert dataset[0].raw_payload_fingerprint is not None


# --- Anti-lookahead: forward outcome construction ------------------------------------------------


def test_forward_outcome_never_uses_a_row_at_or_before_entry_timestamp():
    entry = _row(0, 1.00, 1.05)
    same_time = _row(0, 5.0, 5.0)  # a wildly different price at the SAME timestamp -- must be excluded
    later = _row(5, 1.05, 1.10)
    outcome = compute_forward_outcome(entry, [same_time, later], horizon=ForwardHorizon("5min", 5, 3))
    assert outcome.exit_bid == 1.05  # picked the real later row, not the same-timestamp decoy


def test_forward_outcome_never_uses_a_different_option_id():
    entry = _row(0, 1.00, 1.05, option_id="opt-1")
    other_contract = _row(5, 99.0, 99.0, option_id="opt-OTHER")
    outcome = compute_forward_outcome(entry, [other_contract], horizon=ForwardHorizon("5min", 5, 3))
    assert outcome.data_limited_reason is not None
    assert outcome.exit_bid is None


def test_forward_outcome_unavailable_when_no_later_observation_exists():
    entry = _row(0, 1.00, 1.05)
    outcome = compute_forward_outcome(entry, [], horizon=ForwardHorizon("5min", 5, 3))
    assert outcome.data_limited_reason is not None
    assert outcome.executable_return_pct is None


def test_forward_outcome_unavailable_when_entry_bid_ask_missing():
    entry = _row(0, None, None)
    later = _row(5, 1.05, 1.10)
    outcome = compute_forward_outcome(entry, [later], horizon=ForwardHorizon("5min", 5, 3))
    assert outcome.data_limited_reason is not None


def test_forward_outcome_unavailable_outside_tolerance():
    entry = _row(0, 1.00, 1.05)
    later = _row(100, 1.05, 1.10)  # far outside the 5min+/-3min window
    outcome = compute_forward_outcome(entry, [later], horizon=ForwardHorizon("5min", 5, 3))
    assert outcome.data_limited_reason is not None


def test_executable_return_uses_bid_ask_never_midpoint():
    entry = _row(0, 1.00, 1.10)  # mid = 1.05
    later = _row(5, 1.20, 1.30)  # mid = 1.25
    outcome = compute_forward_outcome(entry, [later], horizon=ForwardHorizon("5min", 5, 3))
    # executable: buy at entry ask (1.10), sell at exit bid (1.20) -> (1.20-1.10)/1.10
    assert abs(outcome.executable_return_pct - ((1.20 - 1.10) / 1.10)) < 1e-9
    # mid return is a DIFFERENT number -- never conflated
    assert abs(outcome.mid_return_pct - ((1.25 - 1.05) / 1.05)) < 1e-9
    assert outcome.executable_return_pct != outcome.mid_return_pct


def test_mfe_and_mae_computed_from_the_observed_path():
    entry = _row(0, 1.00, 1.05)
    path = [_row(5, 1.10, 1.15), _row(10, 0.80, 0.85), _row(15, 1.05, 1.10)]
    outcome = compute_forward_outcome(entry, path, horizon=ForwardHorizon("15min", 15, 5))
    # mids on path: 1.125, 0.825, 1.075 -- vs entry_ask=1.05
    assert outcome.mfe_pct > 0
    assert outcome.mae_pct < 0


def test_risk_adjusted_outcome_only_defined_with_a_real_adverse_excursion():
    entry = _row(0, 1.00, 1.05)
    only_favorable = [_row(5, 1.10, 1.15)]  # never dips below entry
    outcome = compute_forward_outcome(entry, only_favorable, horizon=ForwardHorizon("5min", 5, 3))
    assert outcome.mae_pct is not None and outcome.mae_pct >= 0
    assert outcome.risk_adjusted_outcome is None


def test_directional_outcome_labels_flat_within_the_disclosed_band():
    entry = _row(0, 1.00, 1.00)
    barely_moved = _row(5, 1.005, 1.005)
    outcome = compute_forward_outcome(entry, [barely_moved], horizon=ForwardHorizon("5min", 5, 3))
    assert outcome.directional_outcome == "FLAT"


def test_underlying_relative_performance_computed_correctly():
    entry = _row(0, 1.00, 1.05, underlying=200.0)
    later = _row(5, 1.10, 1.15, underlying=220.0)  # underlying +10%
    outcome = compute_forward_outcome(entry, [later], horizon=ForwardHorizon("5min", 5, 3))
    assert abs(outcome.underlying_return_pct - 0.10) < 1e-9
    assert outcome.option_minus_underlying_return_pct == outcome.executable_return_pct - outcome.underlying_return_pct


def test_all_horizons_never_crash_on_sparse_data():
    entry = _row(0, 1.00, 1.05)
    later = [_row(5, 1.05, 1.10)]
    outcomes = compute_forward_outcomes_all_horizons(entry, later)
    assert set(outcomes) == {h.label for h in DEFAULT_HORIZONS}
    assert outcomes["5min"].data_limited_reason is None
    assert outcomes["eod"].data_limited_reason is not None
