"""Phase 40, Part 6/7/8/9/10/14/17/21/22/23 -- the per-cycle engine
wrapper: real market-closed/no-opportunity handling, a real entry+exit
through the UNMODIFIED src.orchestrator.run_trading_cycle, capital
constraints, and restart-safe no-duplicate-entry behavior.

Uses the SAME `_FakeMarketData`/`_bullish_underlying`/`_liquid_option_
snapshot` fixture shape tests/test_orchestrator.py already established
(all four MarketDataProvider methods implemented), because
MomentumBreakoutStrategy.scan() needs get_underlying_snapshot for
breakout detection -- unlike the simpler Phase 37/39-style fake market,
which only implements the chain/expiration methods.

IMPORTANT: `MarketSnapshot.data_age_seconds`/`UnderlyingSnapshot.
data_age_seconds` are computed against REAL wall-clock time
(`datetime.now(timezone.utc)`), never against the `now` parameter passed
into `run_trading_cycle` -- so `fetched_at` below is always the real
current time, decoupled from the synthetic business-logic `NOW` used for
market-hours/cutoff checks. (This is also why 4 pre-existing
test_orchestrator.py tests fail today with hardcoded 2026-08-18
fetched_at values as the real clock has moved on -- a known,
pre-existing issue this test file does not touch or rely on.)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.market.data_provider import MarketDataProvider
from src.market.errors import QuoteUnavailableError
from src.market.models import EquityQuote, MarketSnapshot, OptionQuote, UnderlyingSnapshot
from src.paper_trading.engine import (
    CYCLE_OK,
    DATA_UNAVAILABLE,
    INSUFFICIENT_PAPER_CAPITAL,
    MARKET_CLOSED_RESULT,
    NO_QUALIFIED_OPPORTUNITY,
    experiment_paths,
    run_paper_experiment_cycle,
)
from src.paper_trading.experiment_config import build_experiment_config
from src.paper_trading.journal import PAPER_EXPERIMENT_LABEL

NOW = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)  # Tuesday, within regular hours
REAL_NOW = datetime.now(timezone.utc)  # for fetched_at -- data_age_seconds uses real wall clock, not NOW


def _bullish_underlying(symbol="AAPL") -> UnderlyingSnapshot:
    from tests.conftest import make_bars

    return UnderlyingSnapshot(
        quote=EquityQuote(symbol=symbol, last_trade_price=230.0, previous_close=225.0, as_of=NOW),
        bars=tuple(make_bars([220.0, 224.0, 228.0, 231.0])),
        rsi=62.0, rsi_prev=58.0, macd_histogram=0.10, macd_histogram_prev=0.05, ema_fast=230.5, ema_slow=225.0,
        vwap=228.0, volume_ratio=1.4, higher_highs=True, lower_highs=False, breakout_continuation=True,
        failed_breakout=False, fetched_at=REAL_NOW,
    )


def _liquid_option_snapshot(option_id, bid=1.00, ask=1.05, volume=200, open_interest=500) -> MarketSnapshot:
    return MarketSnapshot(
        option=OptionQuote(
            instrument_id=option_id, bid_price=bid, ask_price=ask, last_trade_price=(bid + ask) / 2,
            previous_close=0.90, volume=volume, open_interest=open_interest, as_of=NOW,
        ),
        underlying=EquityQuote(symbol="AAPL", last_trade_price=230.0, previous_close=225.0, as_of=NOW),
        option_bars=(), underlying_bars=(), rsi=None, rsi_prev=None, macd_histogram=None, macd_histogram_prev=None,
        ema_fast=None, ema_slow=None, vwap=None, volume_ratio=None, fetched_at=REAL_NOW,
    )


class FakeMarketData(MarketDataProvider):
    """Implements ALL FOUR MarketDataProvider methods -- needed to exercise
    a real strategy entry (unlike a chain-only fake)."""

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
    """Combines what run_observation_cycle needs (get_equity_quotes /
    get_option_quotes) with what run_trading_cycle's Hood-sync step needs
    (get_option_positions / get_option_instruments) -- the same real
    HoodToolClient serves both callers in engine.py's actual production
    path."""

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
        # Fields cover BOTH real consumers of this same chain row:
        # MomentumBreakoutStrategy._select_contract only reads "id"/
        # "strike_price"; the Phase 37 recorder's select_observation_
        # contracts additionally needs "type"/"expiration_date" (and
        # tolerates the rest) -- a real Robinhood chain row carries all of
        # these at once, so the fake must too.
        chain_candidates={"AAPL": [{
            "id": "opt-aapl-1", "strike_price": "230.0000", "type": "call",
            "expiration_date": expiration.isoformat(), "state": "active", "tradability": "tradable",
        }]},
        option_snapshots={"opt-aapl-1": _liquid_option_snapshot("opt-aapl-1")},
    )


def _empty_market():
    return FakeMarketData()


def _config(tmp_path, *, universe=("AAPL",), starting_capital_usd=1000.0):
    return build_experiment_config(now=NOW, universe=universe, starting_capital_usd=starting_capital_usd)


def _paths(tmp_path, experiment_id):
    return experiment_paths(experiment_id, base_dir=tmp_path / "paper_experiments")


# --- Market closed / no opportunity ----------------------------------------------------------


def test_market_closed_short_circuits_with_no_paper_decision(tmp_path, paper_settings):
    saturday = datetime(2026, 8, 15, 15, 0, tzinfo=timezone.utc)
    config = _config(tmp_path)
    result = run_paper_experiment_cycle(
        config=config, client=FakeClient(), market=_empty_market(), base_settings=paper_settings, now=saturday,
        paths=_paths(tmp_path, config.experiment_id),
    )
    assert result.outcome == MARKET_CLOSED_RESULT
    assert result.observation_cycle_id is None
    assert result.new_trades == ()
    assert result.account_snapshot is None


def test_no_candidates_returns_no_qualified_opportunity_not_a_forced_trade(tmp_path, paper_settings):
    config = _config(tmp_path)
    result = run_paper_experiment_cycle(
        config=config, client=FakeClient(), market=_empty_market(), base_settings=paper_settings, now=NOW,
        paths=_paths(tmp_path, config.experiment_id),
    )
    assert result.outcome == NO_QUALIFIED_OPPORTUNITY
    assert result.new_trades == ()
    assert result.observation_cycle_id is not None  # a real observation cycle still ran


# --- Real entry ----------------------------------------------------------------------------------


def test_real_bullish_setup_opens_a_full_paper_experiment_trade_record(tmp_path, paper_settings):
    config = _config(tmp_path)
    result = run_paper_experiment_cycle(
        config=config, client=FakeClient(), market=_bullish_market(), base_settings=paper_settings, now=NOW,
        paths=_paths(tmp_path, config.experiment_id),
    )
    assert result.outcome == CYCLE_OK
    assert len(result.new_trades) == 1
    trade = result.new_trades[0]
    assert trade.label == PAPER_EXPERIMENT_LABEL
    assert trade.symbol == "AAPL"
    assert trade.option_id == "opt-aapl-1"
    assert trade.entry_fill == 1.05  # the real simulated fill -- the ask, never a midpoint
    assert trade.entry_bid == 1.00
    assert trade.entry_ask == 1.05
    assert trade.quantity >= 1
    assert trade.exit_timestamp is None  # still open
    assert trade.strategy_id == config.strategy_id
    assert trade.strategy_content_hash == config.strategy_content_hash


def test_entry_is_tied_to_the_real_observation_cycle_that_produced_it(tmp_path, paper_settings):
    config = _config(tmp_path)
    result = run_paper_experiment_cycle(
        config=config, client=FakeClient(), market=_bullish_market(), base_settings=paper_settings, now=NOW,
        paths=_paths(tmp_path, config.experiment_id),
    )
    assert result.new_trades[0].entry_observation_cycle_id == result.observation_cycle_id


def test_account_snapshot_reflects_cash_committed_to_the_new_open_position(tmp_path, paper_settings):
    config = _config(tmp_path)
    result = run_paper_experiment_cycle(
        config=config, client=FakeClient(), market=_bullish_market(), base_settings=paper_settings, now=NOW,
        paths=_paths(tmp_path, config.experiment_id),
    )
    snapshot = result.account_snapshot
    trade = result.new_trades[0]
    committed = trade.entry_fill * trade.quantity * 100
    assert snapshot.cash_usd == pytest.approx(1000.0 - committed, abs=0.01)
    # equity should be close to starting capital (marked at the same real bid/ask this cycle)
    assert snapshot.equity_usd == pytest.approx(1000.0, abs=committed)


def test_no_structure_other_than_long_call_or_long_put_is_ever_recorded(tmp_path, paper_settings):
    """Part 8: options-only, defined-risk structures only. The frozen
    momentum-breakout strategy only ever emits long_call, so this proves
    the engine's own defensive UNSUPPORTED_STRUCTURE check never fires a
    false positive against the real strategy's actual output."""
    config = _config(tmp_path)
    result = run_paper_experiment_cycle(
        config=config, client=FakeClient(), market=_bullish_market(), base_settings=paper_settings, now=NOW,
        paths=_paths(tmp_path, config.experiment_id),
    )
    assert result.unsupported_structures == ()


# --- Capital constraint -----------------------------------------------------------------------


def test_insufficient_capital_never_forces_a_trade(tmp_path, paper_settings):
    """A starting capital far below one contract's cost (100x the ask)
    must never force an entry -- RiskManager.check_position_size (reused,
    unmodified) rejects it via the experiment's own capped
    max_position_size_usd."""
    config = _config(tmp_path, starting_capital_usd=1.0)  # $1 -- one AAPL call at $1.05 ask costs $105
    result = run_paper_experiment_cycle(
        config=config, client=FakeClient(), market=_bullish_market(), base_settings=paper_settings, now=NOW,
        paths=_paths(tmp_path, config.experiment_id),
    )
    assert result.new_trades == ()
    assert result.outcome in (NO_QUALIFIED_OPPORTUNITY, INSUFFICIENT_PAPER_CAPITAL)


# --- Restart safety / no duplicate entry ------------------------------------------------------


def test_a_second_cycle_never_duplicates_the_still_open_position(tmp_path, paper_settings):
    """Simulates the next real-time tick (or a restart) against the SAME
    persisted experiment paths: RiskManager's own 'no existing position in
    this underlying/contract' check (unmodified, reused) blocks a second
    entry into the same already-open contract -- Part 23's 'never
    duplicate a trade' holds structurally, not just at the trade-store
    dedup layer."""
    config = _config(tmp_path)
    paths = _paths(tmp_path, config.experiment_id)
    first = run_paper_experiment_cycle(
        config=config, client=FakeClient(), market=_bullish_market(), base_settings=paper_settings, now=NOW,
        paths=paths,
    )
    assert len(first.new_trades) == 1

    second = run_paper_experiment_cycle(
        config=config, client=FakeClient(), market=_bullish_market(), base_settings=paper_settings,
        now=NOW + timedelta(minutes=5), paths=paths,
    )
    assert second.new_trades == ()

    from src.paper_trading.journal import PaperExperimentTradeStore

    all_trades = PaperExperimentTradeStore(paths.experiment_trades_file).load_all()
    open_trades = [t for t in all_trades if t.exit_timestamp is None]
    assert len(open_trades) == 1  # still exactly one open position on this contract, never two


def test_state_reloaded_from_disk_by_a_brand_new_store_instance_after_a_simulated_restart(tmp_path, paper_settings):
    config = _config(tmp_path)
    paths = _paths(tmp_path, config.experiment_id)
    run_paper_experiment_cycle(
        config=config, client=FakeClient(), market=_bullish_market(), base_settings=paper_settings, now=NOW,
        paths=paths,
    )

    from src.paper_trading.equity_curve import EquitySnapshotStore
    from src.paper_trading.journal import PaperExperimentTradeStore

    # Brand-new store instances, same paths -- simulates a fresh Python process.
    fresh_trades = PaperExperimentTradeStore(paths.experiment_trades_file)
    fresh_equity = EquitySnapshotStore(paths.equity_curve_file)
    assert len(fresh_trades.load_all()) == 1
    assert fresh_equity.latest() is not None
