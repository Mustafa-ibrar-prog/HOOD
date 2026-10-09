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

_VALID_KEY = "0x" + "a" * 64
# Fixed, fictional base for the UNIT tests below (check_entry_retry_guard
# is pure logic over injected `now`/timestamps -- real wall-clock time
# is irrelevant there). The run_cycle()-level SCENARIO tests further
# down compute their own real datetime.now(timezone.utc) instead,
# because BinaryMarket.data_age_seconds/seconds_to_close -- read by
# risk.py's freshness/cutoff checks -- always use the REAL wall clock
# internally, never a test-injected `now`.
_NOW = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)


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


def test_reconciled_submitted_with_a_resulting_position_is_not_blocked(tmp_path):
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

    decision = check_entry_retry_guard(
        pending_store, position_store, condition_id="c1", outcome="YES", candidate_max_price=0.40,
        cooldown_seconds=120, min_price_change=0.02, now=_NOW,
    )
    assert decision.blocked is False


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

    def set_market(self, market: BinaryMarket | None) -> None:
        self._market = market

    def find_active_btc_market(self, *, now=None) -> BinaryMarket:
        if self._market is None:
            raise NoActiveMarketError("no market open right now")
        return self._market

    def get_resolution(self, condition_id: str) -> str | None:
        return None

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
        close_time=now + timedelta(minutes=10), fetched_at=now, yes_bid=0.60, yes_ask=0.62,
    )
    defaults.update(overrides)
    return BinaryMarket(**defaults)


def _live_harness(tmp_path: Path, market: BinaryMarket, placer: _FakePlacer, **settings_overrides):
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
    history.mids = [0.50, 0.55, 0.60]  # a clear qualifying YES momentum setup
    btc_price_store_path = tmp_path / "btc.json"
    from src.polymarket.btc_market_data import BtcPriceHistoryStore
    btc_price_store = BtcPriceHistoryStore(btc_price_store_path)
    return dict(
        settings=settings, client=client, strategy=strategy, risk_manager=risk, gateway=gateway,
        decision_logger=logger, state_store=state_store, position_store=position_store,
        pending_store=pending_store, history=history, btc_price_store=btc_price_store,
    )


def test_scenario_1_unknown_fill_status_does_not_trigger_an_immediate_duplicate_buy(tmp_path):
    now = datetime.now(timezone.utc)
    market = _market(yes_bid=0.60, yes_ask=0.62)
    placer = _FakePlacer([SubmissionOutcome(ok=True, exchange_order_id="ex-1", raw_status="matched")])
    harness = _live_harness(tmp_path, market, placer)
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
    market = _market(yes_bid=0.60, yes_ask=0.62)
    placer = _FakePlacer([SubmissionOutcome(ok=False, exchange_order_id=None, raw_status=None, error_code="not_enough_balance", error_message="nope")])
    harness = _live_harness(tmp_path, market, placer)

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
    market = _market(yes_bid=0.60, yes_ask=0.62)
    placer = _FakePlacer([
        SubmissionOutcome(ok=False, exchange_order_id=None, raw_status=None, error_code="not_enough_balance", error_message="nope"),
        SubmissionOutcome(ok=True, exchange_order_id="ex-2", raw_status="matched"),
    ])
    harness = _live_harness(tmp_path, market, placer, POLYMARKET_ENTRY_RETRY_COOLDOWN_SECONDS="600")
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
    market_a = _market(condition_id="market-a", token_id_yes="ya", token_id_no="na", yes_bid=0.60, yes_ask=0.62)
    placer = _FakePlacer([
        SubmissionOutcome(ok=False, exchange_order_id=None, raw_status=None, error_code="not_enough_balance", error_message="nope"),
        SubmissionOutcome(ok=True, exchange_order_id="ex-3", raw_status="matched"),
    ])
    harness = _live_harness(tmp_path, market_a, placer)
    harness["client"].set_fill_result("ex-3", FillResult(
        order_id="ex-3", status="filled", requested_shares=10.0, filled_shares=10.0, avg_fill_price=0.62,
    ))

    first = run_cycle(**harness, now=now)
    assert first.entered is False
    assert len(placer.place_order_calls) == 1

    # A genuinely new 15-minute market -- same price/signal shape, but a
    # DIFFERENT condition_id -- must never be blocked by market-a's guard.
    market_b = _market(condition_id="market-b", token_id_yes="yb", token_id_no="nb", yes_bid=0.60, yes_ask=0.62)
    harness["client"].set_market(market_b)
    harness["history"].observe(market_b)  # resets the mid-price buffer for the new market
    harness["history"].mids = [0.50, 0.55, 0.60]

    second = run_cycle(**harness, now=now + timedelta(seconds=15))
    assert len(placer.place_order_calls) == 2  # market-b's entry was never blocked by market-a's guard
    assert second.entered is True
