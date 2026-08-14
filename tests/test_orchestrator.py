"""End-to-end tests for the trading-cycle orchestrator: MARKET SCAN → FIND
SETUP → PAPER ENTRY → MONITOR → HOLD/EXIT/TARGET_EXIT/STOP → LOG →
SYNC WITH ROBINHOOD — all against fakes, all in paper mode, zero real
network/MCP/order calls.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.market.data_provider import MarketDataProvider
from src.market.errors import QuoteUnavailableError
from src.market.models import EquityQuote, MarketSnapshot, OptionQuote, UnderlyingSnapshot
from src.orchestrator import run_trading_cycle
from src.position_manager.store import PaperPositionStore
from src.risk.store import DailyRiskState, RiskStateStore
from tests.conftest import make_bars, make_position

NOW = datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc)  # Tuesday, 11:00 ET — within hours, before cutoff
TODAY = NOW.date()


def _bullish_underlying(symbol="AAPL") -> UnderlyingSnapshot:
    return UnderlyingSnapshot(
        quote=EquityQuote(symbol=symbol, last_trade_price=230.0, previous_close=225.0, as_of=NOW),
        bars=tuple(make_bars([220.0, 224.0, 228.0, 231.0])),
        rsi=62.0,
        rsi_prev=58.0,
        macd_histogram=0.10,
        macd_histogram_prev=0.05,
        ema_fast=230.5,
        ema_slow=225.0,
        vwap=228.0,
        volume_ratio=1.4,
        higher_highs=True,
        lower_highs=False,
        breakout_continuation=True,
        failed_breakout=False,
        fetched_at=NOW,
    )


def _liquid_option_snapshot(option_id, bid=1.00, ask=1.05, volume=200, open_interest=500) -> MarketSnapshot:
    return MarketSnapshot(
        option=OptionQuote(
            instrument_id=option_id,
            bid_price=bid,
            ask_price=ask,
            last_trade_price=(bid + ask) / 2,
            previous_close=0.90,
            volume=volume,
            open_interest=open_interest,
            as_of=NOW,
        ),
        underlying=EquityQuote(symbol="AAPL", last_trade_price=230.0, previous_close=225.0, as_of=NOW),
        option_bars=(),
        underlying_bars=(),
        rsi=None,
        rsi_prev=None,
        macd_histogram=None,
        macd_histogram_prev=None,
        ema_fast=None,
        ema_slow=None,
        vwap=None,
        volume_ratio=None,
        fetched_at=NOW,
    )


class _FakeMarketData(MarketDataProvider):
    def __init__(self, *, underlying_snapshots=None, option_snapshots=None, expirations=None, chain_candidates=None):
        self.underlying_snapshots = underlying_snapshots or {}
        self.option_snapshots = option_snapshots or {}
        self.expirations = expirations or {}
        self.chain_candidates = chain_candidates or {}
        self.calls: list[tuple] = []

    def get_market_snapshot(self, option_id, underlying_symbol, now=None):
        self.calls.append(("get_market_snapshot", option_id))
        if option_id not in self.option_snapshots:
            raise QuoteUnavailableError(f"no snapshot configured for {option_id}")
        return self.option_snapshots[option_id]

    def get_underlying_snapshot(self, symbol, now=None):
        self.calls.append(("get_underlying_snapshot", symbol))
        if symbol not in self.underlying_snapshots:
            raise QuoteUnavailableError(f"no snapshot configured for {symbol}")
        return self.underlying_snapshots[symbol]

    def get_option_expirations(self, underlying_symbol):
        self.calls.append(("get_option_expirations", underlying_symbol))
        return self.expirations.get(underlying_symbol, [])

    def get_option_chain_candidates(self, underlying_symbol, **filters):
        self.calls.append(("get_option_chain_candidates", underlying_symbol))
        return self.chain_candidates.get(underlying_symbol, [])


class _FakeHoodClient:
    def __init__(self, positions=None, instruments=None):
        self.positions = positions or []
        self.instruments = instruments or []
        self.calls: list[str] = []

    def get_option_positions(self, account_number, nonzero=None, **kwargs):
        self.calls.append("get_option_positions")
        return {"data": {"positions": self.positions}, "guide": "..."}

    def get_option_instruments(self, ids=None, **kwargs):
        self.calls.append("get_option_instruments")
        return {"data": {"instruments": self.instruments}, "guide": "..."}


@pytest.fixture
def empty_market():
    return _FakeMarketData()


@pytest.fixture
def empty_hood_client():
    return _FakeHoodClient()


def test_skips_outside_market_hours(paper_settings, empty_market, empty_hood_client):
    saturday = datetime(2026, 8, 15, 15, 0, tzinfo=timezone.utc)
    report = run_trading_cycle(settings=paper_settings, market_data=empty_market, hood_client=empty_hood_client, now=saturday)
    assert report.ran is False
    assert "market hours" in report.skipped_reason.lower()


def test_skips_when_no_account_number_configured(paper_settings, empty_market, empty_hood_client):
    env_settings = paper_settings
    # Build a settings variant with no account number configured.
    from src.config.settings import Settings

    no_account = Settings.from_env(
        env={
            "TRADING_MODE": "paper",
            "LOG_DIR": str(Path(env_settings.log_dir)),
            "DECISION_LOG_FILE": env_settings.decision_log_file,
            "APP_LOG_FILE": env_settings.app_log_file,
            "RISK_STATE_FILE": env_settings.risk_state_file,
            "PAPER_POSITIONS_FILE": env_settings.paper_positions_file,
        }
    )
    report = run_trading_cycle(settings=no_account, market_data=empty_market, hood_client=empty_hood_client, now=NOW)
    assert report.ran is False
    assert "account_number" in report.skipped_reason.lower()


def test_full_cycle_finds_setup_and_opens_a_paper_position(paper_settings, empty_hood_client):
    expiration = TODAY + timedelta(days=14)
    market = _FakeMarketData(
        underlying_snapshots={"AAPL": _bullish_underlying()},
        expirations={"AAPL": [expiration]},
        chain_candidates={"AAPL": [{"id": "opt-aapl-1", "strike_price": "230.0000"}]},
        option_snapshots={"opt-aapl-1": _liquid_option_snapshot("opt-aapl-1")},
    )

    report = run_trading_cycle(settings=paper_settings, market_data=market, hood_client=empty_hood_client, now=NOW)

    assert report.ran is True
    assert report.scan_candidate_count == 1
    assert report.new_entries == ["opt-aapl-1"]

    store = PaperPositionStore(Path(paper_settings.paper_positions_file))
    positions = store.load()
    assert len(positions) == 1
    assert positions[0].option_id == "opt-aapl-1"
    assert positions[0].entry_price == 1.05  # filled at the ask, per the paper gateway's simulation


def test_entries_still_allowed_before_local_cutoff_even_when_utc_clock_is_later(paper_settings, empty_hood_client):
    """Regression test for a real bug caught during live verification: a
    raw UTC `now` (e.g. 18:00 UTC) is numerically past the 15:30 cutoff
    value even though the actual ET local time (14:00 ET) is not — the
    orchestrator must localize before any cutoff/hours comparison, not
    compare a UTC clock directly against an ET boundary."""
    utc_now = datetime(2026, 8, 18, 18, 0, tzinfo=timezone.utc)  # 14:00 ET — before the 15:30 ET cutoff
    expiration = utc_now.date() + timedelta(days=14)
    market = _FakeMarketData(
        underlying_snapshots={"AAPL": _bullish_underlying()},
        expirations={"AAPL": [expiration]},
        chain_candidates={"AAPL": [{"id": "opt-aapl-1", "strike_price": "230.0000"}]},
        option_snapshots={"opt-aapl-1": _liquid_option_snapshot("opt-aapl-1")},
    )

    report = run_trading_cycle(settings=paper_settings, market_data=market, hood_client=empty_hood_client, now=utc_now)

    assert report.ran is True
    assert report.new_entries == ["opt-aapl-1"]


def test_no_entries_when_daily_trade_limit_already_hit(paper_settings, empty_hood_client):
    expiration = TODAY + timedelta(days=14)
    market = _FakeMarketData(
        underlying_snapshots={"AAPL": _bullish_underlying()},
        expirations={"AAPL": [expiration]},
        chain_candidates={"AAPL": [{"id": "opt-aapl-1", "strike_price": "230.0000"}]},
        option_snapshots={"opt-aapl-1": _liquid_option_snapshot("opt-aapl-1")},
    )
    risk_store = RiskStateStore(Path(paper_settings.risk_state_file))
    risk_store.save(DailyRiskState(trade_date=TODAY, trades_opened=paper_settings.max_trades_per_day))

    report = run_trading_cycle(settings=paper_settings, market_data=market, hood_client=empty_hood_client, now=NOW)

    assert report.new_entries == []
    assert report.scan_candidate_count == 0  # scanner isn't even run once the gate fails
    store = PaperPositionStore(Path(paper_settings.paper_positions_file))
    assert store.load() == []


def test_existing_paper_position_stop_exits_and_is_removed_from_ledger(paper_settings, empty_hood_client):
    position = make_position(entry_price=0.95, stop_loss_usd=15.0, option_id="opt-losing")
    store = PaperPositionStore(Path(paper_settings.paper_positions_file))
    store.add_position(position)

    losing_snapshot = _liquid_option_snapshot("opt-losing", bid=0.30, ask=0.35)  # pnl = -62.5, past the $15 stop
    market = _FakeMarketData(option_snapshots={"opt-losing": losing_snapshot})

    report = run_trading_cycle(settings=paper_settings, market_data=market, hood_client=empty_hood_client, now=NOW)

    assert report.exits == ["opt-losing"]
    assert store.load() == []  # removed from the ledger

    risk_store = RiskStateStore(Path(paper_settings.risk_state_file))
    state = risk_store.load(today=TODAY)
    assert state.trades_opened == 0  # unchanged — an exit, not a new trade
    assert state.realized_pnl_usd < 0
    assert state.last_trade_was_loss is True


def test_real_synced_position_is_monitored_but_never_paper_traded(paper_settings):
    real_row = {
        "option_id": "opt-real-1",
        "chain_id": "chain-1",
        "chain_symbol": "MSFT",
        "type": "long",
        "quantity": "1.0000",
        "average_price": "2.00",
        "expiration_date": (TODAY + timedelta(days=20)).isoformat(),
        "trade_value_multiplier": "100.0000",
        "opened_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    hood_client = _FakeHoodClient(
        positions=[real_row],
        instruments=[{"id": "opt-real-1", "strike_price": "300.0000", "type": "call"}],
    )
    market = _FakeMarketData(option_snapshots={"opt-real-1": _liquid_option_snapshot("opt-real-1")})

    report = run_trading_cycle(settings=paper_settings, market_data=market, hood_client=hood_client, now=NOW)

    assert report.real_positions_synced == 1
    assert report.monitored_real_count == 1
    # It was never paper-entered or paper-exited — this system doesn't own it:
    assert report.new_entries == []
    assert report.exits == []
    store = PaperPositionStore(Path(paper_settings.paper_positions_file))
    assert store.load() == []


def test_max_new_entries_per_cycle_zero_disables_scanning_entirely(paper_settings, empty_hood_client):
    from src.config.settings import Settings

    no_new_entries = Settings.from_env(
        env={
            "TRADING_MODE": "paper",
            "MAX_NEW_ENTRIES_PER_CYCLE": "0",
            "LOG_DIR": paper_settings.log_dir,
            "DECISION_LOG_FILE": paper_settings.decision_log_file,
            "APP_LOG_FILE": paper_settings.app_log_file,
            "RISK_STATE_FILE": paper_settings.risk_state_file,
            "PAPER_POSITIONS_FILE": paper_settings.paper_positions_file,
            "ROBINHOOD_ACCOUNT_NUMBER": paper_settings.account_number,
        }
    )
    market = _FakeMarketData(underlying_snapshots={"AAPL": _bullish_underlying()})
    report = run_trading_cycle(settings=no_new_entries, market_data=market, hood_client=empty_hood_client, now=NOW)
    assert report.scan_candidate_count == 0
    assert report.new_entries == []
    assert ("get_underlying_snapshot", "AAPL") not in market.calls


def test_market_data_failure_during_monitoring_is_recorded_not_fatal(paper_settings, empty_hood_client):
    position = make_position(option_id="opt-broken")
    store = PaperPositionStore(Path(paper_settings.paper_positions_file))
    store.add_position(position)

    market = _FakeMarketData()  # no snapshot configured -> QuoteUnavailableError on every fetch
    report = run_trading_cycle(settings=paper_settings, market_data=market, hood_client=empty_hood_client, now=NOW)

    assert report.ran is True
    assert report.errors == []  # MarketDataError is caught INSIDE PositionMonitor and turned into a safe HOLD
    assert report.exits == []


def test_never_calls_order_placement_methods(paper_settings, empty_hood_client):
    expiration = TODAY + timedelta(days=14)
    market = _FakeMarketData(
        underlying_snapshots={"AAPL": _bullish_underlying()},
        expirations={"AAPL": [expiration]},
        chain_candidates={"AAPL": [{"id": "opt-aapl-1", "strike_price": "230.0000"}]},
        option_snapshots={"opt-aapl-1": _liquid_option_snapshot("opt-aapl-1")},
    )
    run_trading_cycle(settings=paper_settings, market_data=market, hood_client=empty_hood_client, now=NOW)

    order_related = {"place_option_order", "review_option_order", "cancel_option_order"}
    assert order_related.isdisjoint(set(empty_hood_client.calls))
    assert order_related.isdisjoint({m for m in dir(market) if not m.startswith("_")})
    assert order_related.isdisjoint({m for m in dir(empty_hood_client) if not m.startswith("_")})
    assert paper_settings.is_paper is True


def test_everything_gets_logged(paper_settings, empty_hood_client):
    expiration = TODAY + timedelta(days=14)
    market = _FakeMarketData(
        underlying_snapshots={"AAPL": _bullish_underlying()},
        expirations={"AAPL": [expiration]},
        chain_candidates={"AAPL": [{"id": "opt-aapl-1", "strike_price": "230.0000"}]},
        option_snapshots={"opt-aapl-1": _liquid_option_snapshot("opt-aapl-1")},
    )
    run_trading_cycle(settings=paper_settings, market_data=market, hood_client=empty_hood_client, now=NOW)

    from src.logging.decision_logger import DecisionLogger

    logger = DecisionLogger(path=paper_settings.decision_log_file, also_console=False)
    records = logger.read_all()
    assert any(r["kind"] == "simulated_order" for r in records)  # the paper entry


def test_scan_result_is_logged_even_when_no_candidate_found(paper_settings, empty_hood_client):
    """LOG EVERYTHING must include 'we scanned and found nothing', not
    just cycles that produced a candidate or a trade."""
    market = _FakeMarketData()  # no underlying snapshots configured -> every symbol skipped, no candidates
    run_trading_cycle(settings=paper_settings, market_data=market, hood_client=empty_hood_client, now=NOW)

    from src.logging.decision_logger import DecisionLogger

    logger = DecisionLogger(path=paper_settings.decision_log_file, also_console=False)
    records = logger.read_all()
    assert any(r["kind"] == "decision" and r["decision"] == "NO_TRADE" for r in records)


def test_scan_skip_reason_is_logged_when_trade_limit_hit(paper_settings, empty_hood_client):
    risk_store = RiskStateStore(Path(paper_settings.risk_state_file))
    risk_store.save(DailyRiskState(trade_date=TODAY, trades_opened=paper_settings.max_trades_per_day))
    market = _FakeMarketData(underlying_snapshots={"AAPL": _bullish_underlying()})

    run_trading_cycle(settings=paper_settings, market_data=market, hood_client=empty_hood_client, now=NOW)

    from src.logging.decision_logger import DecisionLogger

    logger = DecisionLogger(path=paper_settings.decision_log_file, also_console=False)
    records = logger.read_all()
    skip_records = [r for r in records if r["kind"] == "decision" and r["decision"] == "NO_TRADE" and "skipped" in r["reason"].lower()]
    assert len(skip_records) == 1
    assert "trade limit" in skip_records[0]["reason"].lower() or "daily trade" in skip_records[0]["reason"].lower()
