from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.polymarket.btc_market_data import BtcPriceHistoryStore
from src.polymarket.client import NoActiveMarketError
from src.polymarket.engine import MarketHistory, run_cycle, settle_resolved_positions
from src.polymarket.gateway import LivePolymarketGateway, PaperPolymarketGateway
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import BinaryMarket, BookLevel, FillResult, OrderBookSnapshot, SubmissionOutcome
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import OpenPosition, PolymarketPositionStore
from src.polymarket.risk import PolymarketRiskManager
from src.polymarket.settings import PolymarketSettings
from src.polymarket.state import DailyPnlStateStore
from src.polymarket.strategy import BtcMomentumStrategy

_VALID_KEY = "0x" + "a" * 64


def _market(**overrides) -> BinaryMarket:
    now = datetime.now(timezone.utc)
    defaults = dict(
        condition_id="c1", question="Will BTC be up?", token_id_yes="y", token_id_no="n",
        close_time=now + timedelta(minutes=10), fetched_at=now, yes_bid=0.60, yes_ask=0.62,
    )
    defaults.update(overrides)
    return BinaryMarket(**defaults)


class _FakeClient:
    """Fakes just enough of PolymarketClient's surface for engine.py's
    tests: market discovery, resolution, the per-outcome order book
    engine.py fetches before every risk check (Task 6), and fill
    status for the live-reconciliation tests (Task 5)."""

    def __init__(self, market: BinaryMarket | None = None, resolution: str | None = None, book_liquidity_shares: float = 1000.0):
        self._market = market
        self._resolution = resolution
        self._book_liquidity_shares = book_liquidity_shares
        self._fill_results: dict[str, FillResult] = {}
        self.find_calls = 0

    def find_active_btc_market(self, *, now=None) -> BinaryMarket:
        self.find_calls += 1
        if self._market is None:
            raise NoActiveMarketError("no market open right now")
        return self._market

    def get_resolution(self, condition_id: str) -> str | None:
        return self._resolution

    def get_order_book(self, token_id: str) -> OrderBookSnapshot:
        market = self._market
        if token_id == market.token_id_yes:
            bid, ask = market.yes_bid, market.yes_ask
        else:
            bid = round(1 - market.yes_ask, 4) if market.yes_ask is not None else None
            ask = round(1 - market.yes_bid, 4) if market.yes_bid is not None else None
        bids = (BookLevel(price=bid, size=self._book_liquidity_shares),) if bid is not None else ()
        asks = (BookLevel(price=ask, size=self._book_liquidity_shares),) if ask is not None else ()
        return OrderBookSnapshot(token_id=token_id, bids=bids, asks=asks, fetched_at=datetime.now(timezone.utc))

    def set_fill_result(self, exchange_order_id: str, fill: FillResult) -> None:
        self._fill_results[exchange_order_id] = fill

    def get_fill_status(self, exchange_order_id: str) -> FillResult:
        return self._fill_results[exchange_order_id]


def _harness(tmp_path: Path, market: BinaryMarket | None, *, recent_mids_seed: list[float] | None = None, book_liquidity_shares: float = 1000.0):
    settings = PolymarketSettings.from_env(env={"POLYMARKET_LOG_DIR": str(tmp_path)})
    client = _FakeClient(market, book_liquidity_shares=book_liquidity_shares)
    strategy = BtcMomentumStrategy()
    risk = PolymarketRiskManager(settings)
    logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    gateway = PaperPolymarketGateway(settings, logger)
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    history = MarketHistory()
    if recent_mids_seed:
        history.observe(market)
        history.mids = list(recent_mids_seed)
    btc_price_store = BtcPriceHistoryStore(tmp_path / "btc.json")
    return dict(
        settings=settings, client=client, strategy=strategy, risk_manager=risk, gateway=gateway,
        decision_logger=logger, state_store=state_store, position_store=position_store,
        pending_store=pending_store, history=history, btc_price_store=btc_price_store,
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
    position = positions[0]
    assert position.outcome == "YES"
    assert position.filled_shares > 0
    # The paper gateway fills at the order's max_price ceiling (best_ask
    # plus the configured slippage allowance), not at the raw best_ask —
    # see engine.py's max_price computation and gateway.py's
    # PaperPolymarketGateway.submit_order().
    expected_max_price = round(min(market.yes_ask * (1 + harness["settings"].max_price_slippage_pct), 0.99), 4)
    assert position.avg_fill_price == pytest.approx(expected_max_price)
    assert position.status == "filled"
    state = harness["state_store"].load(today=datetime.now(timezone.utc).date())
    assert state.trades_opened == 1
    assert state.open_position_count == 1


def test_qualifying_setup_skipped_when_outcome_book_has_no_liquidity(tmp_path):
    """Task 6: even with a clear momentum signal, a trade must be
    refused when the SPECIFIC outcome's own order book can't actually
    absorb it near our ceiling price."""
    market = _market(yes_bid=0.78, yes_ask=0.80)
    harness = _harness(tmp_path, market=market, recent_mids_seed=[0.50, 0.60, 0.70], book_liquidity_shares=1.0)
    # 1 share at ~0.80 is <$1 notional — well below the $25 default minimum.
    report = run_cycle(**harness)
    assert not report.entered
    assert harness["position_store"].load() == []


def test_max_open_positions_blocks_a_second_entry(tmp_path):
    market = _market(yes_bid=0.78, yes_ask=0.80)
    harness = _harness(tmp_path, market=market, recent_mids_seed=[0.50, 0.60, 0.70])
    # Pre-seed an already-open position so the risk gate should block a new one.
    # avg_fill_price=0.75 is deliberate: its 20% profit target (0.90) is
    # ABOVE this market's yes_bid=0.78, so the automatic profit-target
    # exit check (exit_manager.py) correctly leaves it untouched —
    # keeping this test isolated to what it actually tests (the
    # max_open_positions gate), not incidentally exercising the exit path.
    now = datetime.now(timezone.utc)
    harness["position_store"].add_if_absent(OpenPosition(
        condition_id="other", token_id="y", outcome="YES", requested_size_usd=5.0,
        filled_shares=10.0, avg_fill_price=0.75, order_id="paper:seed", client_order_id="seed-1",
        status="filled", opened_at=now, close_time=now + timedelta(minutes=5),
    ))
    state = harness["state_store"].load()
    state.open_position_count = 1
    harness["state_store"].save(state)

    report = run_cycle(**harness)
    assert not report.entered
    assert len(harness["position_store"].load()) == 1  # unchanged — still just the pre-seeded one


def test_max_open_positions_blocks_new_entry_but_never_short_circuits_dynamic_exit(tmp_path):
    """Requirement: MAX_OPEN_POSITIONS may block NEW entries only -- it
    must never short-circuit dynamic-exit evaluation for an EXISTING
    position. engine.run_cycle() already places
    check_and_execute_dynamic_exits() before find_active_btc_market()/
    risk_manager.evaluate_new_trade() (where check_open_positions is
    actually enforced -- see risk.py); this proves that ordering holds
    end to end with real BTC evidence, not just by reading the source.
    A market that would otherwise clearly qualify for a brand-new
    entry is present too, specifically so this test can also confirm
    that entry really was blocked, not merely never attempted."""
    from tests.test_polymarket_dynamic_exit_replay import _REVERSING_CLOSES, _REVERSING_SEED, _feed

    market = _market(yes_bid=0.78, yes_ask=0.80)  # would otherwise qualify for a brand-new entry too
    settings = PolymarketSettings.from_env(env={
        "POLYMARKET_LOG_DIR": str(tmp_path), "POLYMARKET_DYNAMIC_EXIT_ENABLED": "true",
        "POLYMARKET_MAX_OPEN_POSITIONS": "1",
    })
    client = _FakeClient(market)
    strategy = BtcMomentumStrategy()
    risk = PolymarketRiskManager(settings)
    logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    gateway = PaperPolymarketGateway(settings, logger)
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    history = MarketHistory()
    history.observe(market)
    history.mids = [0.50, 0.60, 0.70]
    btc_price_store = BtcPriceHistoryStore(tmp_path / "btc.json")
    end_t = _feed(btc_price_store, _REVERSING_CLOSES, seed=_REVERSING_SEED)  # real, materially-reversing BTC evidence
    now = end_t + timedelta(seconds=5)

    # An EXISTING open position, already at the max_open_positions cap,
    # deeply profitable at the live book (0.78 bid vs 0.36 entry) --
    # under the v2 edge model that huge gain must NOT be what decides
    # anything; only the real, materially-reversing BTC evidence above
    # should.
    position_store.add_if_absent(OpenPosition(
        condition_id="existing-market", token_id="y", outcome="YES", requested_size_usd=5.0,
        filled_shares=10.0, avg_fill_price=0.36, order_id="paper:seed", client_order_id="seed-1",
        status="filled", opened_at=now - timedelta(minutes=5), close_time=now + timedelta(minutes=5),
    ))
    state = state_store.load(today=now.date())
    state.open_position_count = 1
    state_store.save(state)

    report = run_cycle(
        settings=settings, client=client, strategy=strategy, risk_manager=risk, gateway=gateway,
        decision_logger=logger, state_store=state_store, position_store=position_store,
        pending_store=pending_store, history=history, btc_price_store=btc_price_store, now=now,
    )

    assert report.exits_submitted == 1  # the existing position's exit ran and fired despite being AT the cap
    assert not report.entered  # the new entry was still correctly blocked by max_open_positions
    assert position_store.load() == []  # paper mode: the exit fills immediately


def test_delayed_entry_reconciliation_gets_one_cycle_of_grace_before_dynamic_exit(tmp_path):
    """A second live incident this round fixes: an entry order
    submitted in an EARLIER cycle that sat UNKNOWN finally reconciles
    FILLED via reconcile_pending_orders()'s sweep at the top of THIS
    cycle -- creating a position this very call. Dynamic-exit
    evaluation must NOT immediately reverse that stale-thesis entry on
    this same cycle's fresh (here, materially opposing) evidence -- it
    gets the same one-cycle grace an ordinary brand-new entry already
    gets for free (see engine.py/exit_manager.py's module docstrings).
    A second cycle then proves the deferral is exactly one cycle, never
    a permanent shield: the genuinely bad position still exits, just
    one poll interval later."""
    from tests.test_polymarket_dynamic_exit_replay import _REVERSING_CLOSES, _REVERSING_SEED, _feed

    market = _market(yes_bid=0.50, yes_ask=0.52)  # flat -- no NEW entry this cycle, keeps the test focused
    settings = PolymarketSettings.from_env(env={
        "POLYMARKET_LOG_DIR": str(tmp_path), "POLYMARKET_DYNAMIC_EXIT_ENABLED": "true",
    })
    client = _FakeClient(market)
    strategy = BtcMomentumStrategy()
    risk = PolymarketRiskManager(settings)
    logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    gateway = PaperPolymarketGateway(settings, logger)
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    history = MarketHistory()
    btc_price_store = BtcPriceHistoryStore(tmp_path / "btc.json")
    end_t = _feed(btc_price_store, _REVERSING_CLOSES, seed=_REVERSING_SEED)  # real, materially-reversing BTC evidence
    now = end_t + timedelta(seconds=5)

    from src.polymarket.models import OrderRequest, PendingLiveOrder
    order = OrderRequest(
        condition_id="c1", token_id="y", outcome="YES", side="BUY", size_usd=5.0, max_price=0.56,
        close_time=now + timedelta(minutes=10), reason="earlier cycle's entry, went unknown",
    )
    pending = PendingLiveOrder.new(order=order, expiry_seconds=600, now=now - timedelta(minutes=2))
    pending = pending.with_status("submitted", exchange_order_id="ex-delayed-1")
    pending_store.add(pending)
    client.set_fill_result("ex-delayed-1", FillResult(
        order_id="ex-delayed-1", status="filled", requested_shares=7.0, filled_shares=7.0, avg_fill_price=0.56,
    ))

    report = run_cycle(
        settings=settings, client=client, strategy=strategy, risk_manager=risk, gateway=gateway,
        decision_logger=logger, state_store=state_store, position_store=position_store,
        pending_store=pending_store, history=history, btc_price_store=btc_price_store, now=now,
    )

    assert report.reconciled_count == 1  # the delayed order WAS adopted this cycle
    positions = position_store.load()
    assert len(positions) == 1
    assert positions[0].client_order_id == pending.id  # the SAME position, never duplicated/replaced
    assert report.exits_submitted == 0  # deferred -- NOT immediately exited this same cycle
    deferred = [e for e in logger.read_all() if e.get("kind") == "exit_check_deferred"]
    assert len(deferred) == 1

    # A SECOND cycle, evidence unchanged (still materially REVERSING):
    # now evaluated completely normally, with no special-casing -- and,
    # since the evidence genuinely still opposes it, correctly exits.
    second_report = run_cycle(
        settings=settings, client=client, strategy=strategy, risk_manager=risk, gateway=gateway,
        decision_logger=logger, state_store=state_store, position_store=position_store,
        pending_store=pending_store, history=history, btc_price_store=btc_price_store,
        now=now + timedelta(seconds=10),
    )
    assert second_report.exits_submitted == 1
    assert position_store.load() == []  # paper mode: the exit fills immediately


def test_run_cycle_settles_via_resolution_fallback_when_target_was_never_reached(tmp_path):
    """Requirement: keep the existing 15-minute resolution/settlement
    behavior as the fallback whenever a position's profit target is
    never reached before its market closes. Full run_cycle()
    integration: the automatic profit-target exit check
    (exit_manager.py) runs BEFORE this position's close_time arrives,
    never triggers (its target is far above this market's prices), and
    once the market actually closes, the ORIGINAL settlement path —
    completely untouched by this feature — takes over exactly as before."""
    market = _market(yes_bid=0.55, yes_ask=0.57)  # well below the pre-seeded position's own target
    harness = _harness(tmp_path, market=market, recent_mids_seed=[0.50, 0.50, 0.50])
    past_close = datetime.now(timezone.utc) - timedelta(minutes=1)
    harness["position_store"].add_if_absent(OpenPosition(
        condition_id="other-market", token_id="y", outcome="YES", requested_size_usd=5.0,
        filled_shares=10.0, avg_fill_price=0.5, order_id="paper:x", client_order_id="client-1",
        status="filled", opened_at=past_close - timedelta(minutes=15), close_time=past_close,
    ))
    harness["client"]._resolution = "YES"  # the pre-seeded position's market has now resolved

    report = run_cycle(**harness)

    assert report.settled_count == 1  # the fallback path closed it
    assert report.exits_submitted == 0  # the profit-target path never touched it (already gone by then)
    assert harness["position_store"].load() == []
    state = harness["state_store"].load(today=datetime.now(timezone.utc).date())
    assert state.realized_pnl_usd == pytest.approx(5.0)  # 10 shares - $5 cost = $5 profit, exactly as settlement computes


def test_settle_resolved_positions_realizes_a_win(tmp_path):
    client = _FakeClient(market=None, resolution="YES")
    logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    past_close = datetime.now(timezone.utc) - timedelta(minutes=1)
    position_store.add_if_absent(OpenPosition(
        condition_id="c1", token_id="y", outcome="YES", requested_size_usd=5.0,
        filled_shares=10.0, avg_fill_price=0.5, order_id="paper:x", client_order_id="client-1",
        status="filled", opened_at=past_close - timedelta(minutes=15), close_time=past_close,
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
    position_store.add_if_absent(OpenPosition(
        condition_id="c1", token_id="y", outcome="YES", requested_size_usd=5.0,
        filled_shares=10.0, avg_fill_price=0.5, order_id="paper:x", client_order_id="client-1",
        status="filled", opened_at=past_close - timedelta(minutes=15), close_time=past_close,
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
    position_store.add_if_absent(OpenPosition(
        condition_id="c1", token_id="y", outcome="YES", requested_size_usd=5.0,
        filled_shares=10.0, avg_fill_price=0.5, order_id="paper:x", client_order_id="client-1",
        status="filled", opened_at=past_close - timedelta(minutes=15), close_time=past_close,
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


# --- Reconciliation wiring (Task 5) -------------------------------------------

def test_run_cycle_sweeps_and_reconciles_a_prior_cycles_pending_order(tmp_path):
    """Simulates the exact gap Task 5 describes: a PREVIOUS cycle (or a
    separate confirm_and_place() call, possibly after a restart) left a
    PendingLiveOrder with an exchange_order_id but fill_reconciled=False.
    The NEXT run_cycle() call must pick it up and reconcile it BEFORE
    doing anything else, with no dependency on in-memory state from
    whatever created it."""
    market = _market(yes_bid=0.50, yes_ask=0.52)  # flat this cycle — nothing new proposed
    harness = _harness(tmp_path, market=market)
    client, pending_store, position_store, state_store, decision_logger = (
        harness["client"], harness["pending_store"], harness["position_store"], harness["state_store"], harness["decision_logger"],
    )

    from src.polymarket.models import OrderRequest, PendingLiveOrder
    now = datetime.now(timezone.utc)
    order = OrderRequest(
        condition_id="c1", token_id="y", outcome="YES", side="BUY", size_usd=5.0, max_price=0.55,
        close_time=now + timedelta(minutes=10), reason="prior cycle",
    )
    pending = PendingLiveOrder.new(order=order, expiry_seconds=600)
    pending = pending.with_status("submitted", exchange_order_id="ex-prior-1")
    pending_store.add(pending)
    client.set_fill_result("ex-prior-1", FillResult(
        order_id="ex-prior-1", status="filled", requested_shares=10.0, filled_shares=10.0, avg_fill_price=0.5,
    ))

    report = run_cycle(**harness)
    assert report.reconciled_count == 1
    positions = position_store.load()
    assert len(positions) == 1
    assert positions[0].client_order_id == pending.id
    assert pending_store.get(pending.id).fill_reconciled is True


def test_run_cycle_reconciliation_sweep_is_idempotent_across_cycles(tmp_path):
    market = _market(yes_bid=0.50, yes_ask=0.52)
    harness = _harness(tmp_path, market=market)
    client, pending_store = harness["client"], harness["pending_store"]

    from src.polymarket.models import OrderRequest, PendingLiveOrder
    now = datetime.now(timezone.utc)
    order = OrderRequest(
        condition_id="c1", token_id="y", outcome="YES", side="BUY", size_usd=5.0, max_price=0.55,
        close_time=now + timedelta(minutes=10), reason="prior cycle",
    )
    pending = PendingLiveOrder.new(order=order, expiry_seconds=600)
    pending = pending.with_status("submitted", exchange_order_id="ex-prior-1")
    pending_store.add(pending)
    client.set_fill_result("ex-prior-1", FillResult(
        order_id="ex-prior-1", status="filled", requested_shares=10.0, filled_shares=10.0, avg_fill_price=0.5,
    ))

    first = run_cycle(**harness)
    second = run_cycle(**harness)
    assert first.reconciled_count == 1
    assert second.reconciled_count == 0  # already reconciled — no-op, no second position
    assert len(harness["position_store"].load()) == 1


def test_run_cycle_reconciles_immediately_with_live_auto_execute(tmp_path):
    """live_auto_execute=True means the order reaches the exchange
    within the same cycle it's proposed — engine.py must reconcile it
    before returning, not wait for the next sweep."""
    market = _market(yes_bid=0.78, yes_ask=0.80)
    settings = PolymarketSettings.from_env(env={
        "POLYMARKET_LOG_DIR": str(tmp_path), "POLYMARKET_TRADING_MODE": "live",
        "POLYMARKET_LIVE_TRADING_CONFIRMED": "true", "POLYMARKET_LIVE_AUTO_EXECUTE": "true",
        "POLYMARKET_PRIVATE_KEY": _VALID_KEY,
    })
    client = _FakeClient(market)

    class _FakePlacer:
        def place_order(self, order):
            return SubmissionOutcome(ok=True, exchange_order_id="ex-live-1", raw_status="matched")

    client.set_fill_result("ex-live-1", FillResult(
        order_id="ex-live-1", status="filled", requested_shares=5.0 / market.yes_ask, filled_shares=5.0 / market.yes_ask,
        avg_fill_price=market.yes_ask,
    ))
    strategy = BtcMomentumStrategy()
    risk = PolymarketRiskManager(settings)
    logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    from src.execution.emergency_stop import EmergencyStopStore
    stop_store = EmergencyStopStore(tmp_path / "estop.json")
    stop_store.clear(authorized_by="human:test", reason="testing")
    gateway = LivePolymarketGateway(settings, logger, pending_store, order_placer=_FakePlacer(), emergency_stop_store=stop_store)
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    history = MarketHistory()
    history.observe(market)
    history.mids = [0.50, 0.60, 0.70]

    report = run_cycle(
        settings=settings, client=client, strategy=strategy, risk_manager=risk, gateway=gateway,
        decision_logger=logger, state_store=state_store, position_store=position_store,
        pending_store=pending_store, history=history,
        btc_price_store=BtcPriceHistoryStore(tmp_path / "btc.json"),
    )
    assert report.entered
    positions = position_store.load()
    assert len(positions) == 1
    assert positions[0].order_id == "ex-live-1"
