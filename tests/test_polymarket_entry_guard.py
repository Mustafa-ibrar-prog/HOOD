"""Tests for the entry retry/re-entry guard (entry_guard.py) — added
after a live incident showed auto-execute repeatedly resubmitting a
live BUY for the exact same 15-minute market/outcome every cycle
following an unknown or rejected result:

    order_status_unknown -> rejected -> new pending_order
    (repeats on the same market, cycle after cycle)

Two layers, mirroring test_polymarket_exit_manager.py's own style:
  - UNIT tests directly against check_entry_retry_guard()'s pure logic
    (constructed PendingLiveOrder/store state), isolated from a full
    run_cycle().
  - The 4 user-specified end-to-end scenarios, driven through the REAL
    engine.run_cycle() with a LIVE (auto-execute) gateway and a fake
    order placer, confirming client.place_order is called at most once
    per blocked retry.

Never places a real order — PolymarketOrderPlacer is a local fake
throughout; POLYMARKET_LIVE_AUTO_EXECUTE is only ever set true inside
individual tests here, in-process, to exercise the code path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.execution.emergency_stop import EmergencyStopStore
from src.polymarket.client import NoActiveMarketError
from src.polymarket.engine import MarketHistory, run_cycle
from src.polymarket.entry_guard import check_entry_retry_guard
from src.polymarket.gateway import LivePolymarketGateway
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import BinaryMarket, BookLevel, FillResult, OrderBookSnapshot, OrderRequest, PendingLiveOrder, SubmissionOutcome
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import OpenPosition, PolymarketPositionStore
from src.polymarket.risk import PolymarketRiskManager
from src.polymarket.settings import PolymarketSettings
from src.polymarket.state import DailyPnlStateStore
from src.polymarket.strategy import BtcMomentumStrategy
from tests.test_polymarket_dynamic_exit_replay import _strengthening_closes, _ticks_from_minute_closes

_VALID_KEY = "0x" + "a" * 64
# Fixed, fictional base for the UNIT tests below (check_entry_retry_guard
# is pure logic over injected `now`/timestamps -- real wall-clock time
# is irrelevant there). The run_cycle()-level SCENARIO tests further
# down compute their own real datetime.now(timezone.utc) instead,
# because BinaryMarket.data_age_seconds/seconds_to_close -- read by
# risk.py's freshness/cutoff checks -- always use the REAL wall clock
# internally, never a test-injected `now`.
_NOW = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)


def _feed_bullish_btc_near(btc_price_store, *, now: datetime) -> None:
    """Feeds the same real, STRENGTHENING-when-framed-bullish BTC
    price pattern test_polymarket_dynamic_exit_replay.py uses
    (`_strengthening_closes`/seed=5), SHIFTED so its last tick lands
    just before `now` -- unlike that module's own tests (which use a
    fixed historical base time throughout), these scenario tests must
    keep `now` anchored to the REAL wall clock: LivePolymarketGateway.
    submit_order() always stamps a new PendingLiveOrder's created_at
    from the real clock (gateway.py, never a test-injected `now` --
    see its own call site), so entry_guard.py's cooldown-elapsed
    arithmetic (`now - pending.created_at`) only means anything when
    this test's own `now` tracks real time too. Shifting the fixed
    fixture to end near whatever `now` the test is actually using
    satisfies BOTH that constraint AND assess_btc_entry_direction's
    own freshness gate.

    The shift is rounded to a WHOLE number of minutes, deliberately --
    a sub-minute shift would move every tick off the :00/:15/:30/:45-
    second marks the fixture was generated on, re-bucketing some ticks
    across BtcPriceHistoryStore.get_bars()'s own 60s-bucket boundaries
    (anchored to the Unix epoch, not to this fixture). That changes
    the resulting RSI/MACD/EMA values right at this fixture's own
    margin (exactly min_strengthening_signals=2 fired signals) --
    a real, observed flake (intermittent, real-wall-clock-second-
    dependent test failures) this avoids entirely by preserving the
    EXACT bucket alignment the fixture was verified under, regardless
    of what real second `now` happens to land on."""
    ticks, end_t = _ticks_from_minute_closes(_strengthening_closes(), seed=5)
    whole_minutes = (now - end_t - timedelta(seconds=1)) // timedelta(minutes=1)
    shift = timedelta(minutes=whole_minutes)
    for price, at in ticks:
        btc_price_store.record_quote(price, at=at + shift)


def _order(**overrides) -> OrderRequest:
    defaults = dict(
        condition_id="c1", token_id="y", outcome="YES", side="BUY", size_usd=5.0, max_price=0.62,
        close_time=_NOW + timedelta(minutes=10), reason="test",
    )
    defaults.update(overrides)
    return OrderRequest(**defaults)


def _pending(order: OrderRequest, *, status: str, created_at: datetime, **overrides) -> PendingLiveOrder:
    pending = PendingLiveOrder.new(order=order, expiry_seconds=90, now=created_at)
    return pending.with_status(status, **overrides)


# --- Unit tests: check_entry_retry_guard()'s pure logic ---------------------

def test_no_prior_attempt_is_never_blocked(tmp_path):
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    decision = check_entry_retry_guard(
        pending_store, position_store, condition_id="c1", outcome="YES", candidate_max_price=0.62,
        cooldown_seconds=120, min_price_change=0.02, now=_NOW,
    )
    assert decision.blocked is False


def test_awaiting_approval_always_blocks_regardless_of_cooldown_or_price(tmp_path):
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store.add(_pending(_order(max_price=0.40), status="awaiting_approval", created_at=_NOW - timedelta(hours=1)))

    decision = check_entry_retry_guard(
        pending_store, position_store, condition_id="c1", outcome="YES", candidate_max_price=0.90,  # huge price move
        cooldown_seconds=0, min_price_change=0.0, now=_NOW,  # even a zero cooldown/threshold doesn't matter
    )
    assert decision.blocked is True
    assert "awaiting human approval" in decision.reason.lower()


def test_submitted_but_not_yet_reconciled_always_blocks(tmp_path):
    """The 'unknown' case: submitted, but fill_reconciled is still
    False -- must block regardless of elapsed time or price."""
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store.add(_pending(
        _order(max_price=0.40), status="submitted", created_at=_NOW - timedelta(hours=1),
        exchange_order_id="ex-1", fill_reconciled=False,
    ))

    decision = check_entry_retry_guard(
        pending_store, position_store, condition_id="c1", outcome="YES", candidate_max_price=0.90,
        cooldown_seconds=0, min_price_change=0.0, now=_NOW,
    )
    assert decision.blocked is True
    assert "not yet resolved" in decision.reason.lower()


def test_an_open_position_for_this_market_outcome_always_blocks_a_new_entry(tmp_path):
    """The second live incident this guard was fixed for: a prior
    attempt that already succeeded (and still holds an open position)
    must ALWAYS block a new entry for the exact same (condition_id,
    outcome) -- regardless of cooldown or price change, and regardless
    of MAX_OPEN_POSITIONS having "room" for another position elsewhere.
    The old version of this guard explicitly let this case through,
    assuming MAX_OPEN_POSITIONS (a GLOBAL count) would catch it -- it
    doesn't, since it never checks per-market uniqueness."""
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending = _pending(
        _order(max_price=0.40), status="submitted", created_at=_NOW - timedelta(seconds=5),
        exchange_order_id="ex-1", fill_reconciled=True,
    )
    pending_store.add(pending)
    position_store.add_if_absent(OpenPosition(
        condition_id="c1", token_id="y", outcome="YES", requested_size_usd=5.0, filled_shares=10.0,
        avg_fill_price=0.40, order_id="ex-1", client_order_id=pending.id, status="filled",
        opened_at=_NOW, close_time=_NOW + timedelta(minutes=10),
    ))

    # Even a hugely different price, and even a zero cooldown, must
    # never excuse a duplicate position on a market already held.
    decision = check_entry_retry_guard(
        pending_store, position_store, condition_id="c1", outcome="YES", candidate_max_price=0.90,
        cooldown_seconds=0, min_price_change=0.0, now=_NOW,
    )
    assert decision.blocked is True
    assert "already exists" in decision.reason.lower()
    assert decision.blocking_pending_order_id == pending.id


def test_rejected_blocks_within_cooldown_at_the_same_price(tmp_path):
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store.add(_pending(
        _order(max_price=0.40), status="rejected", created_at=_NOW - timedelta(seconds=10),
        decided_at=_NOW - timedelta(seconds=10), fill_reconciled=True,
    ))

    decision = check_entry_retry_guard(
        pending_store, position_store, condition_id="c1", outcome="YES", candidate_max_price=0.40,
        cooldown_seconds=120, min_price_change=0.02, now=_NOW,
    )
    assert decision.blocked is True
    assert "not a materially changed setup" in decision.reason.lower()


def test_rejected_allows_retry_once_cooldown_elapses(tmp_path):
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store.add(_pending(
        _order(max_price=0.40), status="rejected", created_at=_NOW - timedelta(seconds=200),
        decided_at=_NOW - timedelta(seconds=200), fill_reconciled=True,
    ))

    decision = check_entry_retry_guard(
        pending_store, position_store, condition_id="c1", outcome="YES", candidate_max_price=0.40,  # price unchanged
        cooldown_seconds=120, min_price_change=0.02, now=_NOW,
    )
    assert decision.blocked is False
    assert "cooldown" in decision.reason.lower()


def test_rejected_allows_retry_within_cooldown_if_price_materially_changed(tmp_path):
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store.add(_pending(
        _order(max_price=0.40), status="rejected", created_at=_NOW - timedelta(seconds=10),
        decided_at=_NOW - timedelta(seconds=10), fill_reconciled=True,
    ))

    decision = check_entry_retry_guard(
        pending_store, position_store, condition_id="c1", outcome="YES", candidate_max_price=0.50,  # +0.10 move
        cooldown_seconds=120, min_price_change=0.02, now=_NOW,
    )
    assert decision.blocked is False
    assert "materially changed" in decision.reason.lower()


def test_a_different_outcome_on_the_same_market_is_never_blocked(tmp_path):
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store.add(_pending(
        _order(outcome="YES", max_price=0.40), status="rejected", created_at=_NOW - timedelta(seconds=10),
        decided_at=_NOW - timedelta(seconds=10), fill_reconciled=True,
    ))

    decision = check_entry_retry_guard(
        pending_store, position_store, condition_id="c1", outcome="NO", candidate_max_price=0.40,
        cooldown_seconds=120, min_price_change=0.02, now=_NOW,
    )
    assert decision.blocked is False


def test_a_different_market_is_never_blocked_by_this_markets_guard(tmp_path):
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store.add(_pending(
        _order(condition_id="c1", max_price=0.40), status="rejected", created_at=_NOW - timedelta(seconds=10),
        decided_at=_NOW - timedelta(seconds=10), fill_reconciled=True,
    ))

    decision = check_entry_retry_guard(
        pending_store, position_store, condition_id="c2", outcome="YES", candidate_max_price=0.40,
        cooldown_seconds=120, min_price_change=0.02, now=_NOW,
    )
    assert decision.blocked is False


def test_sell_pending_orders_for_the_same_market_are_ignored(tmp_path):
    """The exit side's own pending SELL orders must never be mistaken
    for a prior ENTRY attempt -- exit_manager.py owns its own,
    completely separate idempotency guard."""
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store.add(_pending(
        _order(side="SELL", max_price=0.40), status="rejected", created_at=_NOW - timedelta(seconds=10),
        decided_at=_NOW - timedelta(seconds=10), fill_reconciled=True,
    ))

    decision = check_entry_retry_guard(
        pending_store, position_store, condition_id="c1", outcome="YES", candidate_max_price=0.40,
        cooldown_seconds=120, min_price_change=0.02, now=_NOW,
    )
    assert decision.blocked is False


# --- End-to-end: the 4 user-specified scenarios via run_cycle() ------------

class _FakeLiveClient:
    """Mirrors PolymarketClient's surface for a LIVE run_cycle():
    market discovery, order book, resolution, and fill status. Order
    SUBMISSION itself goes through a separate fake order_placer (see
    _FakePlacer below) -- this client is never the one that places an
    order (consistent with gateway.py's own "only _submit_pending calls
    place_order" boundary)."""

    def __init__(self, market: BinaryMarket | None, *, book_liquidity_shares: float = 1000.0):
        self._market = market
        self._book_liquidity_shares = book_liquidity_shares
        self._fill_results: dict[str, FillResult] = {}
        # Every market this fake has ever been told about, keyed by EACH
        # of its own tokens -- a real exchange always has a live, correct
        # order book for every still-open token, regardless of which
        # market find_active_btc_market() most recently discovered.
        # set_market() only ever used to REPLACE "the current market" for
        # discovery purposes; it must never erase an earlier market's own
        # token pricing out from under a position that's still open on
        # it, or an exit check reads the WRONG market's price for a
        # position it doesn't belong to.
        self._markets_by_token: dict[str, BinaryMarket] = {}
        if market is not None:
            self._register_market(market)

    def _register_market(self, market: BinaryMarket) -> None:
        self._markets_by_token[market.token_id_yes] = market
        self._markets_by_token[market.token_id_no] = market

    def set_market(self, market: BinaryMarket | None) -> None:
        self._market = market
        if market is not None:
            self._register_market(market)

    def find_active_btc_market(self, *, now=None) -> BinaryMarket:
        if self._market is None:
            raise NoActiveMarketError("no market open right now")
        return self._market

    def get_resolution(self, condition_id: str) -> str | None:
        return None

    def get_order_book(self, token_id: str) -> OrderBookSnapshot:
        market = self._markets_by_token.get(token_id, self._market)
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


class _FakePlacer:
    """The ONLY thing that would ever reach a real exchange -- a local
    fake throughout these tests. `outcomes` is a queue consumed one
    call at a time; the last entry repeats once exhausted."""

    def __init__(self, outcomes: list[SubmissionOutcome]):
        self._outcomes = list(outcomes)
        self.place_order_calls: list[OrderRequest] = []

    def place_order(self, order: OrderRequest) -> SubmissionOutcome:
        self.place_order_calls.append(order)
        if len(self._outcomes) > 1:
            return self._outcomes.pop(0)
        return self._outcomes[0]


def _market(**overrides) -> BinaryMarket:
    """Defaults fetched_at/close_time off the REAL wall clock -- unlike
    the unit tests above, BinaryMarket.data_age_seconds/seconds_to_close
    (read by risk.py's freshness/cutoff checks, exercised end to end by
    the run_cycle() scenario tests below) always compare against REAL
    datetime.now(timezone.utc) internally, never a test-injected `now`."""
    now = datetime.now(timezone.utc)
    defaults = dict(
        condition_id="c1", question="Will BTC be up?", token_id_yes="y", token_id_no="n",
        # close_time within the simple-entry 300s window, and yes_ask
        # >= the 0.70 threshold (see simple_entry_signal.py) -- the
        # ONLY production entry-direction logic as of this round. A
        # tight 2-cent spread so risk.py's own check_spread never
        # independently blocks these (unrelated to what each test
        # actually exercises).
        close_time=now + timedelta(seconds=200), fetched_at=now, yes_bid=0.72, yes_ask=0.74,
    )
    defaults.update(overrides)
    return BinaryMarket(**defaults)


def _live_harness(tmp_path: Path, market: BinaryMarket, placer: _FakePlacer, *, now: datetime | None = None, **settings_overrides):
    now = now or datetime.now(timezone.utc)
    env = dict(
        POLYMARKET_LOG_DIR=str(tmp_path), POLYMARKET_TRADING_MODE="live", POLYMARKET_PRIVATE_KEY=_VALID_KEY,
        POLYMARKET_LIVE_TRADING_CONFIRMED="true", POLYMARKET_LIVE_AUTO_EXECUTE="true",
    )
    env.update(settings_overrides)
    settings = PolymarketSettings.from_env(env=env)
    client = _FakeLiveClient(market)
    strategy = BtcMomentumStrategy()
    risk = PolymarketRiskManager(settings)
    logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    estop = EmergencyStopStore(tmp_path / "estop.json")
    estop.clear(authorized_by="test", reason="test")
    gateway = LivePolymarketGateway(settings, logger, pending_store, order_placer=placer, emergency_stop_store=estop)
    history = MarketHistory()
    history.observe(market)
    btc_price_store_path = tmp_path / "btc.json"
    from src.polymarket.btc_market_data import BtcPriceHistoryStore
    btc_price_store = BtcPriceHistoryStore(btc_price_store_path)
    # engine.run_cycle()'s entry path is now driven by Coinbase BTC
    # evidence (see btc_entry_signal.py), not Polymarket mid-price
    # history -- feed real, materially-bullish BTC bars, shifted to end
    # near THIS harness's own `now` (see _feed_bullish_btc_near), so
    # every test below gets a qualifying YES candidate by default,
    # exactly like the old `history.mids` seed used to provide. A test
    # that needs a materially DIFFERENT price point (scenario 3) still
    # mutates `history.mids`/the market's own book for THAT purpose --
    # unrelated to entry direction now, but still read by
    # exit_manager's Polymarket microstructure signal.
    _feed_bullish_btc_near(btc_price_store, now=now)
    return dict(
        settings=settings, client=client, strategy=strategy, risk_manager=risk, gateway=gateway,
        decision_logger=logger, state_store=state_store, position_store=position_store,
        pending_store=pending_store, history=history, btc_price_store=btc_price_store,
    )


def test_scenario_1_unknown_fill_status_does_not_trigger_an_immediate_duplicate_buy(tmp_path):
    now = datetime.now(timezone.utc)
    market = _market(yes_bid=0.72, yes_ask=0.74)
    placer = _FakePlacer([SubmissionOutcome(ok=True, exchange_order_id="ex-1", raw_status="matched")])
    harness = _live_harness(tmp_path, market, placer, now=now)
    harness["client"].set_fill_result("ex-1", FillResult(
        order_id="ex-1", status="unknown", requested_shares=0.0, filled_shares=0.0, avg_fill_price=None,
    ))

    first = run_cycle(**harness, now=now)
    assert first.entered is False
    assert len(placer.place_order_calls) == 1

    second = run_cycle(**harness, now=now + timedelta(seconds=15))  # same market, same price, moments later
    assert second.entered is False
    assert len(placer.place_order_calls) == 1  # no duplicate submission


def test_scenario_2_rejected_does_not_trigger_an_immediate_duplicate_buy(tmp_path):
    now = datetime.now(timezone.utc)
    market = _market(yes_bid=0.72, yes_ask=0.74)
    placer = _FakePlacer([SubmissionOutcome(ok=False, exchange_order_id=None, raw_status=None, error_code="not_enough_balance", error_message="nope")])
    harness = _live_harness(tmp_path, market, placer, now=now)

    first = run_cycle(**harness, now=now)
    assert first.entered is False
    assert len(placer.place_order_calls) == 1

    second = run_cycle(**harness, now=now + timedelta(seconds=15))
    assert second.entered is False
    assert len(placer.place_order_calls) == 1  # no duplicate submission

    entries = [e for e in harness["decision_logger"].read_all() if e.get("kind") == "entry_retry_blocked"]
    assert len(entries) == 1


def test_scenario_3_a_materially_changed_price_permits_a_later_retry(tmp_path):
    now = datetime.now(timezone.utc)
    market = _market(yes_bid=0.72, yes_ask=0.74)
    placer = _FakePlacer([
        SubmissionOutcome(ok=False, exchange_order_id=None, raw_status=None, error_code="not_enough_balance", error_message="nope"),
        SubmissionOutcome(ok=True, exchange_order_id="ex-2", raw_status="matched"),
    ])
    harness = _live_harness(tmp_path, market, placer, POLYMARKET_ENTRY_RETRY_COOLDOWN_SECONDS="600", now=now)
    harness["client"].set_fill_result("ex-2", FillResult(
        order_id="ex-2", status="filled", requested_shares=10.0, filled_shares=10.0, avg_fill_price=0.82,
    ))

    first = run_cycle(**harness, now=now)
    assert first.entered is False
    assert len(placer.place_order_calls) == 1

    # The market moves meaningfully -- a real new ask, well past the
    # min_price_change threshold, still within the long cooldown window.
    harness["client"].set_market(_market(yes_bid=0.80, yes_ask=0.82))
    harness["history"].mids = [0.50, 0.65, 0.80]

    second = run_cycle(**harness, now=now + timedelta(seconds=15))
    assert len(placer.place_order_calls) == 2  # the retry was allowed through
    assert second.entered is True


def test_scenario_4_a_genuinely_new_market_is_not_blocked_by_the_previous_markets_guard(tmp_path):
    now = datetime.now(timezone.utc)
    market_a = _market(condition_id="market-a", token_id_yes="ya", token_id_no="na", yes_bid=0.72, yes_ask=0.74)
    placer = _FakePlacer([
        SubmissionOutcome(ok=False, exchange_order_id=None, raw_status=None, error_code="not_enough_balance", error_message="nope"),
        SubmissionOutcome(ok=True, exchange_order_id="ex-3", raw_status="matched"),
    ])
    harness = _live_harness(tmp_path, market_a, placer, now=now)
    harness["client"].set_fill_result("ex-3", FillResult(
        order_id="ex-3", status="filled", requested_shares=10.0, filled_shares=10.0, avg_fill_price=0.62,
    ))

    first = run_cycle(**harness, now=now)
    assert first.entered is False
    assert len(placer.place_order_calls) == 1

    # A genuinely new 15-minute market -- same price/signal shape, but a
    # DIFFERENT condition_id -- must never be blocked by market-a's guard.
    market_b = _market(condition_id="market-b", token_id_yes="yb", token_id_no="nb", yes_bid=0.72, yes_ask=0.74)
    harness["client"].set_market(market_b)
    harness["history"].observe(market_b)  # resets the mid-price buffer for the new market
    harness["history"].mids = [0.50, 0.55, 0.60]

    second = run_cycle(**harness, now=now + timedelta(seconds=15))
    assert len(placer.place_order_calls) == 2  # market-b's entry was never blocked by market-a's guard
    assert second.entered is True


# --- The second live incident, reproduced exactly and fixed ----------------
# order D0B9C7Y7JZ8H -> unknown -> (later) position_opened 7 @ $0.69
# order D0B9RW0CJZ8H -> unknown -> (later) position_opened 7 @ $0.63
# (same condition_id, same outcome) -- see entry_guard.py's module docstring.

def test_unknown_then_retry_cycle_blocked_then_original_resolves_filled(tmp_path):
    """Exactly reproduces the live incident's state machine:
      1. order #1 submitted, fill status unknown.
      2. a retry cycle (same market, same price, moments later, still
         unknown) -- the second BUY attempt MUST be blocked.
      3. order #1's fill status becomes authoritatively FILLED (a later
         reconcile_pending_orders() sweep) -- the position is adopted,
         never duplicated.
      4. a THIRD cycle, now that a position exists, must ALSO refuse a
         new entry -- this is the exact case the old guard got wrong."""
    now = datetime.now(timezone.utc)
    market = _market(yes_bid=0.72, yes_ask=0.74)
    placer = _FakePlacer([SubmissionOutcome(ok=True, exchange_order_id="ex-1", raw_status="matched")])
    # MAX_OPEN_POSITIONS=2 -- the exact real-incident configuration.
    # With the default of 1, risk.py's own MAX_OPEN_POSITIONS check
    # would ALSO block step 4 for an unrelated reason (no "room" at
    # all), masking whether THIS guard's new duplicate-position check
    # is what's actually doing the work.
    harness = _live_harness(tmp_path, market, placer, POLYMARKET_MAX_OPEN_POSITIONS="2", now=now)
    harness["client"].set_fill_result("ex-1", FillResult(
        order_id="ex-1", status="unknown", requested_shares=0.0, filled_shares=0.0, avg_fill_price=None,
    ))

    first = run_cycle(**harness, now=now)
    assert first.entered is False
    assert len(placer.place_order_calls) == 1
    assert harness["position_store"].load() == []

    # Step 2: a retry cycle, moments later, still unknown -- MUST be blocked.
    second = run_cycle(**harness, now=now + timedelta(seconds=15))
    assert second.entered is False
    assert len(placer.place_order_calls) == 1  # no second BUY submitted
    blocked_entries = [e for e in harness["decision_logger"].read_all() if e.get("kind") == "entry_retry_blocked"]
    assert len(blocked_entries) == 1
    assert "not yet resolved" in blocked_entries[0]["reason"].lower()

    # Step 3: order #1 authoritatively resolves FILLED (a later sweep).
    # reconcile_pending_orders() runs FIRST in every run_cycle() call
    # (see engine.py), so THIS cycle both (a) adopts order #1's fill
    # into a position, creating it, AND (b) goes on to re-evaluate a
    # fresh entry afterward in that same call -- which now immediately
    # hits the brand-new duplicate-position guard too, since the
    # position it just adopted already exists by the time entry
    # evaluation runs. That is a stronger result than "only the next
    # cycle catches it": the guard closes the gap on the very same
    # cycle the duplicate would otherwise have been attempted.
    harness["client"].set_fill_result("ex-1", FillResult(
        order_id="ex-1", status="filled", requested_shares=7.0, filled_shares=7.0, avg_fill_price=0.69,
    ))
    third = run_cycle(**harness, now=now + timedelta(seconds=30))
    positions = harness["position_store"].load()
    assert len(positions) == 1  # the ORIGINAL order's position, adopted via reconciliation
    assert positions[0].filled_shares == pytest.approx(7.0)
    assert positions[0].avg_fill_price == pytest.approx(0.69)
    assert len(placer.place_order_calls) == 1  # still only the one real submission ever
    assert third.entered is False  # reconciled the prior attempt; never submitted a second real order

    duplicate_blocks_after_third = [
        e for e in harness["decision_logger"].read_all()
        if e.get("kind") == "entry_retry_blocked" and "already exists" in e.get("reason", "").lower()
    ]
    assert len(duplicate_blocks_after_third) == 1  # caught in the SAME cycle the position was adopted

    # Step 4: a FOURTH cycle, with the position still genuinely open --
    # must ALSO refuse a new entry (the exact bug: the old guard let
    # this exact case through).
    fourth = run_cycle(**harness, now=now + timedelta(seconds=45))
    assert fourth.entered is False
    assert len(placer.place_order_calls) == 1  # NEVER a second real order
    assert len(harness["position_store"].load()) == 1  # exactly one position, never duplicated
    duplicate_blocks_after_fourth = [
        e for e in harness["decision_logger"].read_all()
        if e.get("kind") == "entry_retry_blocked" and "already exists" in e.get("reason", "").lower()
    ]
    assert len(duplicate_blocks_after_fourth) == 2  # one more than after the third cycle -- blocked again


def test_unknown_then_authoritative_rejected_then_retry_permitted_after_cooldown(tmp_path):
    """UNKNOWN -> authoritative REJECTED (a real exchange cancellation/
    rejection discovered on reconciliation, not the gateway-level
    rejection) -> retry blocked within the cooldown -> retry permitted
    once the cooldown elapses."""
    now = datetime.now(timezone.utc)
    market = _market(yes_bid=0.72, yes_ask=0.74)
    placer = _FakePlacer([
        SubmissionOutcome(ok=True, exchange_order_id="ex-1", raw_status="matched"),
        SubmissionOutcome(ok=True, exchange_order_id="ex-2", raw_status="matched"),
    ])
    harness = _live_harness(tmp_path, market, placer, POLYMARKET_ENTRY_RETRY_COOLDOWN_SECONDS="60", now=now)
    harness["client"].set_fill_result("ex-1", FillResult(
        order_id="ex-1", status="unknown", requested_shares=0.0, filled_shares=0.0, avg_fill_price=None,
    ))

    first = run_cycle(**harness, now=now)
    assert first.entered is False
    assert len(placer.place_order_calls) == 1

    # Order #1 authoritatively resolves as REJECTED (not unknown, not a fill).
    harness["client"].set_fill_result("ex-1", FillResult(
        order_id="ex-1", status="rejected", requested_shares=0.0, filled_shares=0.0, avg_fill_price=None,
    ))
    second = run_cycle(**harness, now=now + timedelta(seconds=10))  # reconciles #1 as a genuine failure
    assert second.entered is False
    assert harness["position_store"].load() == []

    # Still within the 60s cooldown -- blocked.
    third = run_cycle(**harness, now=now + timedelta(seconds=20))
    assert len(placer.place_order_calls) == 1
    assert third.entered is False

    # Cooldown elapsed -- retry permitted.
    harness["client"].set_fill_result("ex-2", FillResult(
        order_id="ex-2", status="filled", requested_shares=7.0, filled_shares=7.0, avg_fill_price=0.63,
    ))
    fourth = run_cycle(**harness, now=now + timedelta(seconds=75))
    assert len(placer.place_order_calls) == 2  # the retry went through
    assert fourth.entered is True
    positions = harness["position_store"].load()
    assert len(positions) == 1
    assert positions[0].avg_fill_price == pytest.approx(0.63)


def test_two_distinct_markets_can_both_occupy_the_max_open_positions_limit(tmp_path):
    """MAX_OPEN_POSITIONS=2 must still allow two DIFFERENT markets to
    each hold a position -- the duplicate-position fix is scoped to
    the exact (condition_id, outcome) pair, never a blanket limit on
    distinct markets."""
    now = datetime.now(timezone.utc)
    market_a = _market(condition_id="market-a", token_id_yes="ya", token_id_no="na", yes_bid=0.72, yes_ask=0.74)
    placer = _FakePlacer([
        SubmissionOutcome(ok=True, exchange_order_id="ex-a", raw_status="matched"),
        SubmissionOutcome(ok=True, exchange_order_id="ex-b", raw_status="matched"),
    ])
    harness = _live_harness(tmp_path, market_a, placer, POLYMARKET_MAX_OPEN_POSITIONS="2", now=now)
    # avg_fill_price=0.70 keeps market-a's own unchanged bid (0.72) strictly
    # between its stop-loss (0.56) and take-profit target (0.735) in cycle
    # 2's exit check -- this test exercises ONLY the entry-side duplicate-
    # position guard across distinct markets, never take_profit.py's own
    # exit mechanics (covered elsewhere).
    harness["client"].set_fill_result("ex-a", FillResult(
        order_id="ex-a", status="filled", requested_shares=7.0, filled_shares=7.0, avg_fill_price=0.70,
    ))

    first = run_cycle(**harness, now=now)
    assert first.entered is True
    assert len(harness["position_store"].load()) == 1

    market_b = _market(condition_id="market-b", token_id_yes="yb", token_id_no="nb", yes_bid=0.72, yes_ask=0.74)
    harness["client"].set_market(market_b)
    harness["client"].set_fill_result("ex-b", FillResult(
        order_id="ex-b", status="filled", requested_shares=7.0, filled_shares=7.0, avg_fill_price=0.62,
    ))
    harness["history"].observe(market_b)
    harness["history"].mids = [0.50, 0.55, 0.60]

    second = run_cycle(**harness, now=now + timedelta(seconds=15))
    assert second.entered is True  # market-b's entry succeeded too -- at the cap, not over it
    positions = harness["position_store"].load()
    assert len(positions) == 2
    assert {p.condition_id for p in positions} == {"market-a", "market-b"}

    state = harness["state_store"].load(today=now.date())
    assert state.open_position_count == 2  # exactly at MAX_OPEN_POSITIONS=2, both distinct markets
