"""Phase 38 — the campaign orchestrator, run against both the REAL
(empty) Phase 37 stores and a synthetic fixture proving the join/
pipeline mechanics work end to end."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config.settings import Settings
from src.market.data_provider import MarketDataProvider
from src.options.phase38_campaign import default_recorder_stores, run_phase38_campaign
from src.production.decision import DecisionType
from src.research_recorder.recorder import RecorderStores, run_observation_cycle
from src.research_recorder.research_signal import ResultLabel
from src.research_recorder.storage import CycleLogStore, NormalizedOptionStore, NormalizedUnderlyingStore, RawObservationStore, ResearchSignalStore

NOW = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)


def _stores(tmp_path: Path):
    return RecorderStores(
        raw=RawObservationStore(tmp_path / "raw.jsonl"), underlying=NormalizedUnderlyingStore(tmp_path / "u.jsonl"),
        option=NormalizedOptionStore(tmp_path / "o.jsonl"), signal=ResearchSignalStore(tmp_path / "s.jsonl"),
        cycle_log=CycleLogStore(tmp_path / "c.jsonl"),
    )


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


def test_campaign_against_the_real_currently_empty_default_stores():
    """This is the REAL result this phase reports -- the actual
    repository, as it stands today, has never recorded a live
    observation."""
    stores = default_recorder_stores(Path("logs/research_data/phase37"))
    result = run_phase38_campaign(stores=stores)
    assert result.n_dataset_rows == 0
    assert result.n_outcomes == 0
    assert not result.gate_result.passed
    assert "sufficient_sample_size" in result.gate_result.unmet_condition_names


def test_campaign_with_recorded_cycles_but_no_entry_signals_still_not_ready():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        for i in range(5):
            run_observation_cycle(client=FakeClient(), market=FakeMarket(), settings=Settings.from_env(env={"TRADING_MODE": "paper"}), stores=stores, now=NOW + timedelta(minutes=5 * i), universe=["AAPL"], cycle_id=f"cyc-{i}")
        result = run_phase38_campaign(stores=stores)
        assert result.n_dataset_rows == 5
        assert result.n_entry_signals == 0  # no ENTER decision was ever recorded
        assert not result.gate_result.passed


def test_campaign_joins_a_manually_recorded_enter_signal_to_its_real_dataset_row():
    """Proves the entry_rows join logic works: an ENTER signal recorded
    against a real (cycle_id, option_id) pair is correctly matched to
    its causal feature row. Constructs the normalized rows directly
    (rather than via run_observation_cycle, whose own real strategy
    evaluation would auto-record a competing NO_TRADE signal for the
    same cycle_id/strategy_id key and be silently deduplicated against
    a manually-appended ENTER for that same key) so the join can be
    tested in isolation."""
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        from src.research_recorder.normalized_observation import build_normalized_option_observation, build_normalized_underlying_observation
        from src.research_recorder.research_signal import ResearchSignalRecord

        for i in range(3):
            t = NOW + timedelta(minutes=5 * i)
            stores.underlying.append(build_normalized_underlying_observation(
                symbol="AAPL", observation_cycle_id=f"cyc-{i}", observation_timestamp=t,
                quote_row={"last_trade_price": "230.0"},
            ))
            stores.option.append(build_normalized_option_observation(
                option_id="opt-AAPL-230", underlying="AAPL", observation_cycle_id=f"cyc-{i}", observation_timestamp=t,
                market_timezone="America/New_York", quote_row={"bid_price": "1.0", "ask_price": "1.05"},
                chain_row={"type": "call", "strike_price": "230.0", "expiration_date": (NOW.date() + timedelta(days=30)).isoformat(), "state": "active", "tradability": "tradable"},
                underlying_price=230.0,
            ))

        stores.signal.append(ResearchSignalRecord(
            observation_cycle_id="cyc-0", strategy_id="MOMENTUM_BREAKOUT_EXISTING_V1", signal_timestamp=NOW,
            produced_signal=True, underlying="AAPL", candidate_option_id="opt-AAPL-230", decision=DecisionType.ENTER.value,
            features={}, reason="test", label=ResultLabel.HYPOTHETICAL_RESEARCH_DECISION.value,
        ))
        result = run_phase38_campaign(stores=stores)
        assert result.n_entry_signals == 1
        assert result.n_outcomes == 1  # the entry has 2 later observations to compute a 5min outcome from


def test_campaign_result_never_promotes_anything_on_its_own():
    """run_phase38_campaign only EVALUATES -- it never calls
    promote_if_validated/mark_validated itself."""
    import inspect

    from src.options import phase38_campaign

    source = inspect.getsource(phase38_campaign)
    assert "mark_validated" not in source
    assert "promote_if_validated" not in source


def test_default_recorder_stores_points_at_the_documented_convention_path():
    stores = default_recorder_stores(Path("logs/research_data/phase37"))
    assert stores.raw is not None and stores.cycle_log is not None
