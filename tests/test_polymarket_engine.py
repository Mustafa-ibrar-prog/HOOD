from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.polymarket.client import NoActiveMarketError
from src.polymarket.engine import MarketHistory, run_cycle, settle_resolved_positions
from src.polymarket.gateway import PaperPolymarketGateway
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import BinaryMarket
from src.polymarket.positions import OpenPosition, PolymarketPositionStore
from src.polymarket.risk import PolymarketRiskManager
from src.polymarket.settings import PolymarketSettings
from src.polymarket.state import DailyPnlStateStore
from src.polymarket.strategy import BtcMomentumStrategy


def _market(**overrides) -> BinaryMarket:
    now = datetime.now(timezone.utc)
    defaults = dict(
        condition_id="c1", question="Will BTC be up?", token_id_yes="y", token_id_no="n",
        close_time=now + timedelta(minutes=10), fetched_at=now, yes_bid=0.60, yes_ask=0.62,
    )
    defaults.update(overrides)
    return BinaryMarket(**defaults)


class _FakeClient:
    def __init__(self, market: BinaryMarket | None = None, resolution: str | None = None):
        self._market = market
        self._resolution = resolution
        self.find_calls = 0

    def find_active_btc_market(self, *, now=None) -> BinaryMarket:
        self.find_calls += 1
        if self._market is None:
            raise NoActiveMarketError("no market open right now")
        return self._market

    def get_resolution(self, condition_id: str) -> str | None:
        return self._resolution


def _harness(tmp_path: Path, market: BinaryMarket | None, *, recent_mids_seed: list[float] | None = None):
    settings = PolymarketSettings.from_env(env={"POLYMARKET_LOG_DIR": str(tmp_path)})
    client = _FakeClient(market)
    strategy = BtcMomentumStrategy()
    risk = PolymarketRiskManager(settings)
    logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    gateway = PaperPolymarketGateway(settings, logger)
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    history = MarketHistory()
    if recent_mids_seed:
        history.observe(market)
        history.mids = list(recent_mids_seed)
    return dict(
        settings=settings, client=client, strategy=strategy, risk_manager=risk, gateway=gateway,
        decision_logger=logger, state_store=state_store, position_store=position_store, history=history,
    )


def test_no_active_market_is_a_clean_skip_not_an_error(tmp_path):
    harness = _harness(tmp_path, market=None)
    report = run_cycle(**harness)
    assert report.ran
    assert report.skipped_reason is not None
    assert not report.entered


def test_no_setup_logs_no_trade_and_does_not_enter(tmp_path):
    market = _market(yes_bid=0.50, yes_ask=0.52)  # flat, no momentum yet
    harness = _harness(tmp_path, market=market)
    report = run_cycle(**harness)
    assert report.ran
    assert not report.entered
    assert harness["position_store"].load() == []


def test_qualifying_setup_enters_a_paper_position(tmp_path):
    market = _market(yes_bid=0.78, yes_ask=0.80)
    harness = _harness(tmp_path, market=market, recent_mids_seed=[0.50, 0.60, 0.70])
    report = run_cycle(**harness)
    assert report.entered
    positions = harness["position_store"].load()
    assert len(positions) == 1
    assert positions[0].outcome == "YES"
    state = harness["state_store"].load(today=datetime.now(timezone.utc).date())
    assert state.trades_opened == 1
    assert state.open_position_count == 1


def test_max_open_positions_blocks_a_second_entry(tmp_path):
    market = _market(yes_bid=0.78, yes_ask=0.80)
    harness = _harness(tmp_path, market=market, recent_mids_seed=[0.50, 0.60, 0.70])
    # Pre-seed an already-open position so the risk gate should block a new one.
    harness["position_store"].add(OpenPosition(
        condition_id="other", token_id="y", outcome="YES", entry_price=0.5, size_usd=5.0, shares=10.0,
        opened_at=datetime.now(timezone.utc), close_time=datetime.now(timezone.utc) + timedelta(minutes=5),
    ))
    state = harness["state_store"].load()
    state.open_position_count = 1
    harness["state_store"].save(state)

    report = run_cycle(**harness)
    assert not report.entered
    assert len(harness["position_store"].load()) == 1  # unchanged — still just the pre-seeded one


def test_settle_resolved_positions_realizes_a_win(tmp_path):
    client = _FakeClient(market=None, resolution="YES")
    logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    past_close = datetime.now(timezone.utc) - timedelta(minutes=1)
    position_store.add(OpenPosition(
        condition_id="c1", token_id="y", outcome="YES", entry_price=0.5, size_usd=5.0, shares=10.0,
        opened_at=past_close - timedelta(minutes=15), close_time=past_close,
    ))
    state = state_store.load()
    state.open_position_count = 1
    state_store.save(state)

    settled = settle_resolved_positions(client=client, position_store=position_store, state_store=state_store, decision_logger=logger)
    assert settled == 1
    assert position_store.load() == []
    final_state = state_store.load()
    assert final_state.realized_pnl_usd == pytest.approx(5.0)  # 10 shares - $5 cost = $5 profit
    assert final_state.open_position_count == 0


def test_settle_resolved_positions_realizes_a_loss(tmp_path):
    client = _FakeClient(market=None, resolution="NO")
    logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    past_close = datetime.now(timezone.utc) - timedelta(minutes=1)
    position_store.add(OpenPosition(
        condition_id="c1", token_id="y", outcome="YES", entry_price=0.5, size_usd=5.0, shares=10.0,
        opened_at=past_close - timedelta(minutes=15), close_time=past_close,
    ))

    settled = settle_resolved_positions(client=client, position_store=position_store, state_store=state_store, decision_logger=logger)
    assert settled == 1
    final_state = state_store.load()
    assert final_state.realized_pnl_usd == pytest.approx(-5.0)


def test_settle_resolved_positions_leaves_unresolved_markets_alone(tmp_path):
    client = _FakeClient(market=None, resolution=None)  # API hasn't reflected resolution yet
    logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    past_close = datetime.now(timezone.utc) - timedelta(minutes=1)
    position_store.add(OpenPosition(
        condition_id="c1", token_id="y", outcome="YES", entry_price=0.5, size_usd=5.0, shares=10.0,
        opened_at=past_close - timedelta(minutes=15), close_time=past_close,
    ))

    settled = settle_resolved_positions(client=client, position_store=position_store, state_store=state_store, decision_logger=logger)
    assert settled == 0
    assert len(position_store.load()) == 1


def test_market_history_resets_on_a_different_market():
    market1 = _market(condition_id="c1", yes_bid=0.5, yes_ask=0.52)
    market2 = _market(condition_id="c2", yes_bid=0.3, yes_ask=0.32)
    history = MarketHistory()
    history.observe(market1)
    history.observe(market1)
    assert len(history.mids) == 2
    history.observe(market2)
    assert len(history.mids) == 1  # reset for the new market
