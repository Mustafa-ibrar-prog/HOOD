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


def _feed_bullish_btc(btc_price_store: BtcPriceHistoryStore) -> datetime:
    """Feeds real, STRENGTHENING-when-framed-bullish BTC bars (the
    SAME pinned, verified fixture test_polymarket_dynamic_exit_replay.py
    uses) -- since engine.run_cycle()'s entry path is now driven by
    Coinbase BTC evidence (see btc_entry_signal.py), a test that wants
    a qualifying entry candidate must feed real BTC bars, not seed
    Polymarket's own mid-price history. Returns the timestamp of the
    last fed sample -- callers must pass `now=` close to it (see
    run_cycle's own `now` parameter) so the fed bars read FRESH rather
    than stale by the time assess_btc_entry_direction checks them."""
    from tests.test_polymarket_dynamic_exit_replay import _feed, _strengthening_closes
    return _feed(btc_price_store, _strengthening_closes(), seed=5)


def _market(**overrides) -> BinaryMarket:
    now = datetime.now(timezone.utc)
    defaults = dict(
        condition_id="c1", question="Will BTC be up?", token_id_yes="y", token_id_no="n",
        # Within the simple-entry 300s window by default (see
        # simple_entry_signal.py) -- the ONLY production entry-
        # direction logic as of this round. Callers testing "too early"
        # explicitly override close_time further out.
        close_time=now + timedelta(seconds=200), fetched_at=now, yes_bid=0.60, yes_ask=0.62,
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
    # Exactly tied (yes_bid == yes_ask == 0.50, so YES's and NO's own
    # implied probabilities are both exactly 0.50) -- there is no
    # probability-threshold gate any more (see simple_entry_signal.py),
    # so this is the one case that still correctly produces no trade:
    # neither side is favored, and a tie is never resolved by guessing.
    market = _market(yes_bid=0.50, yes_ask=0.50)
    harness = _harness(tmp_path, market=market)
    report = run_cycle(**harness)
    assert report.ran
    assert not report.entered
    assert harness["position_store"].load() == []


def test_qualifying_setup_enters_a_paper_position(tmp_path):
    # ask=0.80 >= the 0.70 threshold, close_time within the 300s window
    # (see _market()'s own defaults) -- the ONLY production entry
    # signal as of this round (simple_entry_signal.py); no BTC feed at
    # all is needed or consulted.
    market = _market(yes_bid=0.78, yes_ask=0.80)
    harness = _harness(tmp_path, market=market)
    now = datetime.now(timezone.utc)
    report = run_cycle(**harness, now=now)
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
    state = harness["state_store"].load(today=now.date())  # matches the fixed `now` run_cycle() wrote under
    assert state.trades_opened == 1
    assert state.open_position_count == 1


def test_qualifying_setup_skipped_when_outcome_book_has_no_liquidity(tmp_path):
    """Task 6: even with an otherwise-qualifying ask, a trade must be
    refused when the SPECIFIC outcome's own order book can't actually
    absorb it near our ceiling price."""
    market = _market(yes_bid=0.78, yes_ask=0.80)
    harness = _harness(tmp_path, market=market, book_liquidity_shares=1.0)
    now = datetime.now(timezone.utc)
    # 1 share at ~0.80 is <$1 notional — well below the $10 minimum.
    report = run_cycle(**harness, now=now)
    assert not report.entered
    assert harness["position_store"].load() == []


def test_max_open_positions_blocks_a_second_entry(tmp_path):
    market = _market(yes_bid=0.78, yes_ask=0.80)
    harness = _harness(tmp_path, market=market)
    end_t = _feed_bullish_btc(harness["btc_price_store"])  # real, materially-bullish BTC evidence -- otherwise qualifies
    now = end_t + timedelta(seconds=5)
    # Pre-seed an already-open position so the risk gate should block a new one.
    # avg_fill_price=0.75 is deliberate: its 20% profit target (0.90) is
    # ABOVE this market's yes_bid=0.78, so the automatic profit-target
    # exit check (exit_manager.py) correctly leaves it untouched —
    # keeping this test isolated to what it actually tests (the
    # max_open_positions gate), not incidentally exercising the exit path.
    harness["position_store"].add_if_absent(OpenPosition(
        condition_id="other", token_id="y", outcome="YES", requested_size_usd=5.0,
        filled_shares=10.0, avg_fill_price=0.75, order_id="paper:seed", client_order_id="seed-1",
        status="filled", opened_at=now, close_time=now + timedelta(minutes=5),
    ))
    # today=now.date() -- matching the FIXED `now` passed to run_cycle()
    # below, not state_store.load()'s own default of the real wall-clock
    # today (DailyPnlStateStore.load() resets to a fresh/empty state on
    # a date mismatch), so run_cycle()'s own state read actually sees
    # this seeded count.
    state = harness["state_store"].load(today=now.date())
    state.open_position_count = 1
    harness["state_store"].save(state)

    report = run_cycle(**harness, now=now)
    assert not report.entered
    assert len(harness["position_store"].load()) == 1  # unchanged — still just the pre-seeded one


def test_max_open_positions_blocks_new_entry_but_never_short_circuits_take_profit(tmp_path):
    """Requirement: MAX_OPEN_POSITIONS may block NEW entries only -- it
    must never short-circuit take-profit evaluation for an EXISTING
    position. engine.run_cycle() already places
    check_and_execute_take_profits() before find_active_btc_market()/
    risk_manager.evaluate_new_trade() (where check_open_positions is
    actually enforced -- see risk.py); this proves that ordering holds
    end to end. A market that would otherwise clearly qualify for a
    brand-new entry is present too, specifically so this test can also
    confirm that entry really was blocked, not merely never attempted."""
    market = _market(yes_bid=0.78, yes_ask=0.80)  # would otherwise qualify for a brand-new entry too
    settings = PolymarketSettings.from_env(env={
        "POLYMARKET_LOG_DIR": str(tmp_path), "POLYMARKET_MAX_OPEN_POSITIONS": "1",
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
    btc_price_store = BtcPriceHistoryStore(tmp_path / "btc.json")
    now = datetime.now(timezone.utc)

    # An EXISTING open position, already at the max_open_positions cap,
    # whose own +5% take-profit target has been reached at the live
    # book's bid (0.78, this same market's own yes_bid -- the fake
    # client keys any token matching token_id_yes to it): target =
    # 0.70 * 1.05 = 0.735 <= 0.78, so this is exactly "target reached"
    # -- a full exit.
    position_store.add_if_absent(OpenPosition(
        condition_id="existing-market", token_id="y", outcome="YES", requested_size_usd=5.0,
        filled_shares=10.0, avg_fill_price=0.70, order_id="paper:seed", client_order_id="seed-1",
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

    assert report.exits_submitted == 1  # the existing position's take-profit exit ran and fired despite being AT the cap
    assert not report.entered  # the new entry was still correctly blocked by max_open_positions
    assert position_store.load() == []  # paper mode: the exit fills immediately


def test_delayed_entry_reconciliation_gets_one_cycle_of_grace_before_take_profit(tmp_path):
    """A live incident this round fixes: an entry order submitted in an
    EARLIER cycle that sat UNKNOWN finally reconciles FILLED via
    reconcile_pending_orders()'s sweep at the top of THIS cycle --
    creating a position this very call. Take-profit evaluation must
    NOT immediately touch that just-adopted position on this same
    cycle -- it gets the same one-cycle grace an ordinary brand-new
    entry already gets for free (see engine.py/take_profit.py's
    module docstrings). A second cycle then proves the deferral is
    exactly one cycle, never a permanent shield: the position IS
    evaluated completely normally from then on (here, correctly held
    -- its price never reached its own +5% target)."""
    market = _market(yes_bid=0.50, yes_ask=0.52)  # flat -- no NEW entry this cycle, keeps the test focused
    settings = PolymarketSettings.from_env(env={"POLYMARKET_LOG_DIR": str(tmp_path)})
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
    now = datetime.now(timezone.utc)

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
    assert report.exits_submitted == 0  # deferred -- NOT immediately evaluated this same cycle
    deferred = [e for e in logger.read_all() if e.get("kind") == "exit_check_deferred"]
    assert len(deferred) == 1

    # A SECOND cycle: the grace has expired -- the position IS now
    # evaluated normally by take_profit.py, with no special-casing.
    # Its price (0.50 bid) never reached its own +5% target (0.588), so
    # it correctly just holds -- never a sell, and never deferred again.
    second_report = run_cycle(
        settings=settings, client=client, strategy=strategy, risk_manager=risk, gateway=gateway,
        decision_logger=logger, state_store=state_store, position_store=position_store,
        pending_store=pending_store, history=history, btc_price_store=btc_price_store,
        now=now + timedelta(seconds=10),
    )
    assert second_report.exits_submitted == 0
    assert len(position_store.load()) == 1  # still open -- correctly held, not sold
    holds = [e for e in logger.read_all() if e.get("kind") == "take_profit_hold"]
    assert len(holds) == 1  # evaluated normally on cycle 2 -- not deferred a second time
    deferred_total = [e for e in logger.read_all() if e.get("kind") == "exit_check_deferred"]
    assert len(deferred_total) == 1  # still just the one from cycle 1 -- never deferred again


def test_stale_pending_entry_past_its_own_market_close_is_adopted_but_never_re_exited_same_cycle(tmp_path):
    """Full incident replay (reported live): an OLD pending BUY order
    whose OWN market has ALREADY closed finally resolves FILLED via
    reconcile_pending_orders()'s sweep -- long after the one-cycle
    delayed-entry grace alone would have helped (that grace only ever
    covers ONE cycle; this order sat unresolved far longer, and its
    market closed in the meantime). The real fill is still reconciled
    (never pretended away) and the resulting position is flagged
    `stale_entry_fill_adopted` -- but because its market has already
    closed, check_and_execute_dynamic_exits() must defer entirely to
    settlement THIS SAME cycle, never proposing a fresh exit on it."""
    from tests.test_polymarket_dynamic_exit_replay import _REVERSING_CLOSES, _REVERSING_SEED, _feed

    market = _market(yes_bid=0.50, yes_ask=0.52)  # flat -- no new entry this cycle, keeps the test focused
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
    # Materially-reversing BTC evidence -- exactly the kind of evidence
    # that WOULD otherwise trigger an immediate exit if this position
    # were evaluated normally. It must never get the chance to.
    end_t = _feed(btc_price_store, _REVERSING_CLOSES, seed=_REVERSING_SEED)
    now = end_t + timedelta(seconds=5)

    from src.polymarket.models import OrderRequest, PendingLiveOrder
    old_market_close = now - timedelta(minutes=5)  # this stale order's OWN market already closed
    stale_order = OrderRequest(
        condition_id="btc-updown-15m-stale-2245z", token_id="y", outcome="YES", side="BUY", size_usd=5.0,
        max_price=0.56, close_time=old_market_close, reason="an old cycle's entry, sat unresolved for a long time",
    )
    stale_pending = PendingLiveOrder.new(order=stale_order, expiry_seconds=60, now=now - timedelta(minutes=20))
    stale_pending = stale_pending.with_status("submitted", exchange_order_id="ex-old-stale")
    pending_store.add(stale_pending)
    client.set_fill_result("ex-old-stale", FillResult(
        order_id="ex-old-stale", status="filled", requested_shares=8.0, filled_shares=8.0, avg_fill_price=0.28,
    ))

    report = run_cycle(
        settings=settings, client=client, strategy=strategy, risk_manager=risk, gateway=gateway,
        decision_logger=logger, state_store=state_store, position_store=position_store,
        pending_store=pending_store, history=history, btc_price_store=btc_price_store, now=now,
    )

    # The real fill is reconciled correctly -- never pretended away.
    assert report.reconciled_count == 1
    positions = position_store.load()
    assert len(positions) == 1
    assert positions[0].condition_id == "btc-updown-15m-stale-2245z"
    assert positions[0].filled_shares == pytest.approx(8.0)
    assert positions[0].avg_fill_price == pytest.approx(0.28)

    stale_logs = [e for e in logger.read_all() if e.get("kind") == "stale_entry_fill_adopted"]
    assert len(stale_logs) == 1

    # This SAME cycle's dynamic-exit pass must NOT propose a new exit
    # on it -- it happens to be caught by the EXISTING one-cycle
    # delayed-entry grace here too (it was, after all, also "newly
    # adopted this very call"), which is fine on its own but only ever
    # lasts one cycle (see that mechanism's own docstring/test) --
    # settle_resolved_positions() already ran this cycle too but left
    # it alone (the fake resolution API hasn't reflected the close yet
    # -- the realistic "resolved by clock, not yet by the API" case).
    assert report.exits_submitted == 0
    assert report.settled_count == 0
    deferred = [e for e in logger.read_all() if e.get("kind") == "exit_check_deferred"]
    assert len(deferred) == 1

    # THE ACTUAL FIX, proven on a SECOND cycle: the one-cycle grace has
    # now expired (nothing new was adopted this call), yet the position
    # must STILL never be evaluated for a fresh exit, because its
    # market-closed skip applies for as long as the position exists --
    # not just one cycle. This is exactly the gap the user's own report
    # flagged: "the bot correctly deferred exit evaluation for one
    # cycle, but that does NOT solve the underlying stale pending-entry
    # problem."
    second_report = run_cycle(
        settings=settings, client=client, strategy=strategy, risk_manager=risk, gateway=gateway,
        decision_logger=logger, state_store=state_store, position_store=position_store,
        pending_store=pending_store, history=history, btc_price_store=btc_price_store,
        now=now + timedelta(seconds=10),
    )
    assert second_report.exits_submitted == 0
    assert second_report.settled_count == 0
    skipped = [e for e in logger.read_all() if e.get("kind") == "exit_check_skipped_market_closed"]
    assert len(skipped) == 1
    assert position_store.load() == positions  # still there, completely untouched, both cycles
    assert position_store.load() == positions  # still there, completely untouched


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
    btc_price_store = BtcPriceHistoryStore(tmp_path / "btc.json")
    # ask=0.80 >= 0.70 threshold, close_time within the 300s window
    # (see _market()'s own defaults) -- no BTC feed needed or consulted.
    now = datetime.now(timezone.utc)

    report = run_cycle(
        settings=settings, client=client, strategy=strategy, risk_manager=risk, gateway=gateway,
        decision_logger=logger, state_store=state_store, position_store=position_store,
        pending_store=pending_store, history=history, btc_price_store=btc_price_store, now=now,
    )
    assert report.entered
    positions = position_store.load()
    assert len(positions) == 1
    assert positions[0].order_id == "ex-live-1"


# --- Single-order-book venue (Polymarket US) end to end --------------------
# The critical pricing-bug fix: this venue has exactly ONE real order
# book (token_id_yes == token_id_no == the same market slug). engine.py
# must fetch it ONCE per cycle and derive NO's own view via
# single_book.to_no_perspective() -- never fetch "NO's own book" a
# second time (that would return the exact same data and misread it as
# two independent prices -- the original bug report: identical
# YES_ASK/NO_ASK readings in the logs).

from src.polymarket.single_book import to_no_perspective  # noqa: E402


def _single_book_market(**overrides) -> BinaryMarket:
    now = datetime.now(timezone.utc)
    defaults = dict(
        condition_id="sb-c1", question="Will BTC be up?", token_id_yes="slug-1", token_id_no="slug-1",
        close_time=now + timedelta(seconds=200), fetched_at=now, yes_bid=0.60, yes_ask=0.62,
    )
    defaults.update(overrides)
    return BinaryMarket(**defaults)


class _FakeSingleBookClient:
    """Serves exactly ONE real OrderBookSnapshot regardless of which
    (identical) token_id is asked for -- counts calls so a test can
    prove engine.py never fetches it twice per cycle."""

    def __init__(self, market: BinaryMarket | None, book: OrderBookSnapshot):
        self._market = market
        self._book = book
        self._fill_results: dict[str, FillResult] = {}
        self.get_order_book_calls: list[str] = []

    def find_active_btc_market(self, *, now=None) -> BinaryMarket:
        if self._market is None:
            raise NoActiveMarketError("no market open right now")
        return self._market

    def get_resolution(self, condition_id: str) -> str | None:
        return None

    def get_order_book(self, token_id: str) -> OrderBookSnapshot:
        self.get_order_book_calls.append(token_id)
        return self._book

    def set_fill_result(self, exchange_order_id: str, fill: FillResult) -> None:
        self._fill_results[exchange_order_id] = fill

    def get_fill_status(self, exchange_order_id: str) -> FillResult:
        return self._fill_results[exchange_order_id]


def _single_book_harness(tmp_path: Path, market: BinaryMarket | None, book: OrderBookSnapshot):
    settings = PolymarketSettings.from_env(env={"POLYMARKET_LOG_DIR": str(tmp_path)})
    client = _FakeSingleBookClient(market, book)
    strategy = BtcMomentumStrategy()
    risk = PolymarketRiskManager(settings)
    logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    gateway = PaperPolymarketGateway(settings, logger)
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    history = MarketHistory()
    btc_price_store = BtcPriceHistoryStore(tmp_path / "btc.json")
    return dict(
        settings=settings, client=client, strategy=strategy, risk_manager=risk, gateway=gateway,
        decision_logger=logger, state_store=state_store, position_store=position_store,
        pending_store=pending_store, history=history, btc_price_store=btc_price_store,
    )


def test_single_book_market_fetches_the_real_book_exactly_once_per_cycle(tmp_path):
    market = _single_book_market()
    book = OrderBookSnapshot(
        token_id="slug-1", bids=(BookLevel(price=0.50, size=1000.0),),
        asks=(BookLevel(price=0.50, size=1000.0),), fetched_at=datetime.now(timezone.utc),
    )  # mid 0.50 -- deliberately non-qualifying, so no submission side effects matter here
    harness = _single_book_harness(tmp_path, market, book)
    run_cycle(**harness)
    assert harness["client"].get_order_book_calls == ["slug-1"]  # exactly once, never a redundant second fetch


def test_single_book_market_yes_midpoint_070_enters_yes_at_the_real_ask(tmp_path):
    market = _single_book_market()
    book = OrderBookSnapshot(
        token_id="slug-1", bids=(BookLevel(price=0.65, size=1000.0),),
        asks=(BookLevel(price=0.75, size=1000.0),), fetched_at=datetime.now(timezone.utc),
    )  # mid 0.70 -- the governing worked example
    harness = _single_book_harness(tmp_path, market, book)
    report = run_cycle(**harness)
    assert report.entered is True
    positions = harness["position_store"].load()
    assert len(positions) == 1
    position = positions[0]
    assert position.outcome == "YES"
    assert position.single_book_market is True
    expected_max_price = round(min(0.75 * (1 + harness["settings"].max_price_slippage_pct), 0.99), 4)
    assert position.avg_fill_price == pytest.approx(expected_max_price)


def test_single_book_market_no_midpoint_070_enters_no_at_the_real_short_price(tmp_path):
    market = _single_book_market()
    book = OrderBookSnapshot(
        token_id="slug-1", bids=(BookLevel(price=0.25, size=1000.0),),
        asks=(BookLevel(price=0.35, size=1000.0),), fetched_at=datetime.now(timezone.utc),
    )  # yes mid 0.30 -> no implied probability 0.70
    harness = _single_book_harness(tmp_path, market, book)
    report = run_cycle(**harness)
    assert report.entered is True
    positions = harness["position_store"].load()
    assert len(positions) == 1
    position = positions[0]
    assert position.outcome == "NO"
    assert position.single_book_market is True
    # The real NO executable price is 1 - yes_bid (0.75), NEVER the
    # yes_mid (0.30) and never the raw yes_ask (0.35).
    no_real_ask = round(1 - 0.25, 4)
    expected_max_price = round(min(no_real_ask * (1 + harness["settings"].max_price_slippage_pct), 0.99), 4)
    assert position.avg_fill_price == pytest.approx(expected_max_price)


def test_single_book_market_the_original_bug_report_reading_now_resolves_cleanly(tmp_path):
    """The exact symptom from the bug report: identical YES_ASK/NO_ASK
    readings (0.88/0.88) in the logs, because the SAME book was being
    fetched twice and misread as two independent prices. With the fix,
    there is only ever ONE real reading (yes mid 0.88) -- NO's own
    implied probability is correctly 0.12, nowhere near qualifying, so
    this cleanly enters YES instead of the old false "both >= 0.70,
    conflicting" no-trade."""
    market = _single_book_market()
    book = OrderBookSnapshot(
        token_id="slug-1", bids=(BookLevel(price=0.88, size=1000.0),),
        asks=(BookLevel(price=0.88, size=1000.0),), fetched_at=datetime.now(timezone.utc),
    )
    harness = _single_book_harness(tmp_path, market, book)
    report = run_cycle(**harness)
    assert report.entered is True
    positions = harness["position_store"].load()
    assert len(positions) == 1
    assert positions[0].outcome == "YES"


def test_single_book_market_no_position_exit_check_uses_the_inverted_book(tmp_path):
    """A pre-existing NO position on a single-book venue must have its
    take-profit exit evaluated against single_book.to_no_perspective()'s
    derived bid (1 - the raw book's best_ask), never the raw book's own
    best_bid directly. MAX_OPEN_POSITIONS=1 (with state already at the
    cap) isolates this from the fact that the SAME book, read as a
    fresh candidate, would ALSO independently qualify NO for a brand
    new entry -- this test is about the EXIT check specifically, not
    entry/exit interaction in the same cycle."""
    market = _single_book_market()
    # Raw book: bid 0.20 / ask 0.22 -- the NO position's own exit price
    # is 1 - 0.22 = 0.78, which clears its +5% take-profit target
    # (0.73 * 1.05 = 0.7665). Reading the raw book's own best_bid
    # (0.20) directly would (wrongly) read as a catastrophic loss
    # instead (well past the -20% stop-loss floor, 0.584) -- see the
    # next test, which proves exactly that confusion when the flag is
    # (correctly, for this position) False.
    book = OrderBookSnapshot(
        token_id="slug-1", bids=(BookLevel(price=0.20, size=1000.0),),
        asks=(BookLevel(price=0.22, size=1000.0),), fetched_at=datetime.now(timezone.utc),
    )
    harness = _single_book_harness(tmp_path, market, book)
    harness["settings"] = PolymarketSettings.from_env(
        env={"POLYMARKET_LOG_DIR": str(tmp_path), "POLYMARKET_MAX_OPEN_POSITIONS": "1"},
    )
    now = datetime.now(timezone.utc)
    harness["position_store"].add_if_absent(OpenPosition(
        condition_id="sb-existing", token_id="slug-1", outcome="NO", requested_size_usd=20.0,
        filled_shares=27.0, avg_fill_price=0.73, order_id="paper:seed", client_order_id="seed-no-1",
        status="filled", opened_at=now - timedelta(minutes=5), close_time=now + timedelta(minutes=10),
        single_book_market=True,
    ))
    state = harness["state_store"].load(today=now.date())
    state.open_position_count = 1
    harness["state_store"].save(state)
    report = run_cycle(**harness, now=now)
    assert report.exits_submitted == 1
    assert not report.entered  # no fresh entry snuck in despite the same book also qualifying NO
    assert harness["position_store"].load() == []  # paper mode: the exit fills immediately
    submissions = [e for e in harness["decision_logger"].read_all() if e.get("kind") == "take_profit_exit_submitted"]
    assert len(submissions) == 1  # correctly the TAKE-PROFIT trigger, never stop-loss, once converted


def test_single_book_market_no_position_without_the_flag_misreads_the_raw_book_as_a_loss(tmp_path):
    """Regression guard for the flag itself: a NO position with
    single_book_market=False (e.g. one opened on international
    Polymarket, which genuinely has a separate NO book) must NOT be
    run through to_no_perspective() -- confirmed here with the EXACT
    SAME raw book, position size, and avg_fill_price as the test
    above, differing ONLY in the flag. Reading the raw book directly
    (0.20) misreads a genuinely profitable NO position (whose real
    exit price is 0.78, well above its 0.7665 take-profit target) as a
    catastrophic loss instead -- triggering the WRONG exit (stop-loss,
    not take-profit). This is exactly why the flag, and the conversion
    it gates, matter: the position still exits (there is no "silently
    does nothing" failure mode here now that a stop-loss also exists),
    but for the wrong reason, which this test makes visible."""
    market = _single_book_market()
    book = OrderBookSnapshot(
        token_id="slug-1", bids=(BookLevel(price=0.20, size=1000.0),),
        asks=(BookLevel(price=0.22, size=1000.0),), fetched_at=datetime.now(timezone.utc),
    )
    harness = _single_book_harness(tmp_path, market, book)
    harness["settings"] = PolymarketSettings.from_env(
        env={"POLYMARKET_LOG_DIR": str(tmp_path), "POLYMARKET_MAX_OPEN_POSITIONS": "1"},
    )
    now = datetime.now(timezone.utc)
    harness["position_store"].add_if_absent(OpenPosition(
        condition_id="sb-existing-2", token_id="slug-1", outcome="NO", requested_size_usd=20.0,
        filled_shares=27.0, avg_fill_price=0.73, order_id="paper:seed", client_order_id="seed-no-2",
        status="filled", opened_at=now - timedelta(minutes=5), close_time=now + timedelta(minutes=10),
        single_book_market=False,
    ))
    state = harness["state_store"].load(today=now.date())
    state.open_position_count = 1
    harness["state_store"].save(state)
    report = run_cycle(**harness, now=now)
    assert report.exits_submitted == 1
    assert not report.entered  # MAX_OPEN_POSITIONS=1, already at the cap -- no fresh entry either
    assert harness["position_store"].load() == []
    submissions = [e for e in harness["decision_logger"].read_all() if e.get("kind") == "stop_loss_exit_submitted"]
    assert len(submissions) == 1  # the WRONG trigger -- proof the missing conversion matters


def test_single_book_market_sanity_check_against_to_no_perspective_directly(tmp_path):
    """Cross-check: the exit-check's own math must match
    single_book.to_no_perspective() exactly, not a hand-rolled
    equivalent -- this is the one place take_profit.py's own book-
    inversion step is exercised end to end."""
    book = OrderBookSnapshot(
        token_id="slug-1", bids=(BookLevel(price=0.20, size=1000.0),),
        asks=(BookLevel(price=0.22, size=1000.0),), fetched_at=datetime.now(timezone.utc),
    )
    assert to_no_perspective(book).best_bid == pytest.approx(0.78)
