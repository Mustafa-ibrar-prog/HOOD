"""Control-flow tests for scripts/one_shot_real_dynamic_exit_test.py --
fakes throughout (the same _FakeSDKClient boundary objects
tests/test_polymarket_manual_us_test.py already uses), never a real
network call, never real money.

The entry leg is the EXACT, unmodified run_manual_test() already
covered by tests/test_polymarket_manual_us_test.py -- these tests exist
to exercise what's NEW here: the open-position/pending-order refusal,
the entry-must-reconcile-before-any-exit-attempt gate, wiring the
(mocked) BTC evidence + the real evaluator into a REAL position, the
auto_exit_enabled-respecting exit submission, and the order-count
runtime guard.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import scripts.one_shot_real_dynamic_exit_test as one_shot  # noqa: E402
from src.polymarket.exit_manager import DEFAULT_MIN_WEAKENING_SIGNALS_FOR_EXIT  # noqa: E402
from src.polymarket.logger import PolymarketDecisionLogger  # noqa: E402
from src.polymarket.pending import PolymarketPendingOrderStore  # noqa: E402
from src.polymarket.positions import OpenPosition, PolymarketPositionStore  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402
from src.polymarket.state import DailyPnlStateStore  # noqa: E402
from src.polymarket.us_client import PolymarketUSClient  # noqa: E402
from src.strategy.evidence import MomentumState  # noqa: E402
from tests.test_polymarket_exit_manager import _assessment  # noqa: E402
from tests.test_polymarket_manual_us_test import (  # noqa: E402
    _LIVE_CREDS,
    _settings as _manual_test_settings,
    _stores_with_emergency_stop_cleared,
)
from tests.test_polymarket_us_client import (  # noqa: E402
    _FakeAccount,
    _FakeEvents,
    _FakeMarkets,
    _FakeOrders,
    _FakeSDKClient,
    _book_level,
    _book_response,
    _event,
    _order_response,
)


def _real_now() -> datetime:
    return datetime.now(timezone.utc)


def _settings(slug: str, **overrides) -> PolymarketSettings:
    return _manual_test_settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true", **overrides,
    )


def _book_bid_060_ask_062(size: float = 100.0) -> dict:
    # Deliberately above the 0.50 entry fill price below, so the
    # position is profitable by the time the (fake) exit evaluation
    # reads this same book -- entry fill price and "current" order
    # book are two separate real-world data points even in this test.
    return _book_response([_book_level("0.60", size)], [_book_level("0.62", size)])


def _sdk_with_entry_fill(slug: str, *, entry_order_id: str = "ord-entry-1", avg_px: str = "0.50") -> _FakeSDKClient:
    now = _real_now()
    event = _event(slug=slug, start=now - timedelta(minutes=1), end=now + timedelta(minutes=10), market_slug=slug)
    orders = _FakeOrders(
        preview_response={"order": {"id": "preview-ok"}},
        create_response={"id": entry_order_id, "executions": []},
        retrieve_responses={
            entry_order_id: _order_response("ORDER_STATE_FILLED", quantity=10, cum=10, avg_px=avg_px, order_id=entry_order_id),
        },
    )
    return _FakeSDKClient(
        events=_FakeEvents({slug: {"event": event}}),
        markets=_FakeMarkets(books={slug: _book_bid_060_ask_062()}),
        orders=orders,
        account=_FakeAccount(response={"balances": [{"currency": "USD", "currentBalance": 100.0}]}),
    )


def _patch_assess_btc_market(monkeypatch, state: MomentumState, *, signal_count: int = 5):
    def _fake(bars, order_book, recent_mids, *, outcome, now=None, max_bar_age_seconds=300.0, feed_source="manual", **_kwargs):
        return _assessment(state, signal_count=signal_count)

    monkeypatch.setattr(one_shot, "assess_btc_market", _fake)


def _patch_coinbase_unreachable(monkeypatch):
    def _raise(self, *, limit):
        raise one_shot.CoinbaseBtcQuoteSourceError("sandbox egress blocked")

    monkeypatch.setattr(one_shot.CoinbaseBtcQuoteSource, "get_recent_candles", _raise)


def _patch_coinbase_fake_candles(monkeypatch, *, count: int = 40):
    from src.market.models import PriceBar

    now = _real_now()

    def _fake(self, *, limit):
        return [
            PriceBar(
                start_time=now - timedelta(minutes=count - i), open=60000.0, high=60001.0, low=59999.0,
                close=60000.0, volume=1.0,
            )
            for i in range(count)
        ]

    monkeypatch.setattr(one_shot.CoinbaseBtcQuoteSource, "get_recent_candles", _fake)


def _run_one_shot(settings, client, tmp_path, *, confirm_live=True, outcome="YES", amount=5.0, max_price=0.65):
    stores = _stores_with_emergency_stop_cleared(tmp_path)
    return one_shot.run_one_shot_test(
        settings=settings, client=client, outcome=outcome, amount=amount, max_price=max_price,
        confirm_live=confirm_live, decision_logger=stores["decision_logger"], state_store=stores["state_store"],
        position_store=stores["position_store"], pending_store=stores["pending_store"],
        emergency_stop_store=stores["emergency_stop_store"], unknown_status_retry_delay_seconds=0.0,
    ), stores


# --- Refuses before even attempting an entry ----------------------------------

def test_refuses_when_an_open_position_already_exists(tmp_path, monkeypatch, capsys):
    slug = "one-shot-existing-position"
    _patch_coinbase_fake_candles(monkeypatch)
    sdk = _sdk_with_entry_fill(slug)
    settings = _settings(slug)
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores_with_emergency_stop_cleared(tmp_path)
    stores["position_store"].add_if_absent(OpenPosition(
        condition_id=slug, token_id=slug, outcome="YES", requested_size_usd=5.0, filled_shares=10.0,
        avg_fill_price=0.50, order_id="existing", client_order_id="existing", status="filled",
        opened_at=_real_now(), close_time=_real_now() + timedelta(minutes=5),
    ))

    rc = one_shot.run_one_shot_test(
        settings=settings, client=client, outcome="YES", amount=5.0, max_price=0.65, confirm_live=True,
        decision_logger=stores["decision_logger"], state_store=stores["state_store"],
        position_store=stores["position_store"], pending_store=stores["pending_store"],
        emergency_stop_store=stores["emergency_stop_store"],
    )

    assert rc == 1
    assert "already exists" in capsys.readouterr().out
    assert sdk.orders.create_calls == []


def test_refuses_when_a_pending_order_is_already_awaiting_approval(tmp_path, monkeypatch, capsys):
    from src.polymarket.models import OrderRequest, PendingLiveOrder

    slug = "one-shot-existing-pending"
    sdk = _sdk_with_entry_fill(slug)
    settings = _settings(slug)
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores_with_emergency_stop_cleared(tmp_path)
    order = OrderRequest(
        condition_id=slug, token_id=slug, outcome="YES", side="BUY", size_usd=5.0, max_price=0.65,
        close_time=_real_now() + timedelta(minutes=5), reason="other",
    )
    stores["pending_store"].add(PendingLiveOrder.new(order=order, expiry_seconds=600))

    rc = one_shot.run_one_shot_test(
        settings=settings, client=client, outcome="YES", amount=5.0, max_price=0.65, confirm_live=True,
        decision_logger=stores["decision_logger"], state_store=stores["state_store"],
        position_store=stores["position_store"], pending_store=stores["pending_store"],
        emergency_stop_store=stores["emergency_stop_store"],
    )

    assert rc == 1
    assert "already awaiting approval" in capsys.readouterr().out
    assert sdk.orders.create_calls == []


# --- Preflight-only: nothing submitted ----------------------------------------

def test_preflight_only_run_submits_nothing(tmp_path, monkeypatch, capsys):
    slug = "one-shot-preflight-only"
    sdk = _sdk_with_entry_fill(slug)
    settings = _settings(slug)
    client = PolymarketUSClient(settings, sdk_client=sdk)

    rc, stores = _run_one_shot(settings, client, tmp_path, confirm_live=False)

    assert rc == 0
    assert "Preflight-only run" in capsys.readouterr().out
    assert sdk.orders.create_calls == []
    assert stores["position_store"].load() == []


# --- Entry not authoritatively reconciled -> exit never attempted ------------

def test_entry_fill_status_unknown_aborts_before_any_exit_attempt(tmp_path, monkeypatch, capsys):
    slug = "one-shot-unknown-fill"
    now = _real_now()
    event = _event(slug=slug, start=now - timedelta(minutes=1), end=now + timedelta(minutes=10), market_slug=slug)
    orders = _FakeOrders(
        preview_response={"order": {"id": "preview-ok"}},
        create_response={"id": "ord-unknown-1", "executions": []},
        retrieve_responses={"ord-unknown-1": _order_response("ORDER_STATE_SOMETHING_NEW", quantity=10, cum=0, order_id="ord-unknown-1")},
    )
    sdk = _FakeSDKClient(
        events=_FakeEvents({slug: {"event": event}}), markets=_FakeMarkets(books={slug: _book_bid_060_ask_062()}),
        orders=orders, account=_FakeAccount(response={"balances": [{"currency": "USD", "currentBalance": 100.0}]}),
    )
    settings = _settings(slug)
    client = PolymarketUSClient(settings, sdk_client=sdk)

    rc, stores = _run_one_shot(settings, client, tmp_path)

    assert rc == 1
    out = capsys.readouterr().out
    assert "ABORTING: the entry did not complete cleanly" in out
    assert "No exit will be attempted" in out
    assert stores["position_store"].load() == []
    assert sdk.orders.create_calls == [orders.create_calls[0]]  # exactly one create() call -- never a second


# --- HOLD: evaluator does not approve an exit ---------------------------------

def test_evaluator_hold_leaves_the_real_position_open_and_submits_no_exit(tmp_path, monkeypatch, capsys):
    slug = "one-shot-hold"
    _patch_coinbase_fake_candles(monkeypatch)
    _patch_assess_btc_market(monkeypatch, MomentumState.INSUFFICIENT_DATA)
    sdk = _sdk_with_entry_fill(slug)
    settings = _settings(slug)
    client = PolymarketUSClient(settings, sdk_client=sdk)

    rc, stores = _run_one_shot(settings, client, tmp_path)

    assert rc == 0
    out = capsys.readouterr().out
    assert "Dynamic-exit decision: HOLD" in out
    assert "REMAINS OPEN" in out
    positions = stores["position_store"].load()
    assert len(positions) == 1
    assert positions[0].condition_id == slug
    assert len(sdk.orders.create_calls) == 1  # the entry only -- no exit submitted


# --- EXIT eligible, auto_exit_enabled=False -> stops at awaiting_approval ----

def test_evaluator_exit_with_auto_exit_disabled_stops_at_awaiting_approval(tmp_path, monkeypatch, capsys):
    slug = "one-shot-exit-awaiting-approval"
    _patch_coinbase_fake_candles(monkeypatch)
    _patch_assess_btc_market(monkeypatch, MomentumState.REVERSING, signal_count=DEFAULT_MIN_WEAKENING_SIGNALS_FOR_EXIT)
    sdk = _sdk_with_entry_fill(slug)
    settings = _settings(slug, POLYMARKET_AUTO_EXIT_ENABLED="false")
    assert settings.live_auto_execute is False
    assert settings.auto_exit_enabled is False
    client = PolymarketUSClient(settings, sdk_client=sdk)

    rc, stores = _run_one_shot(settings, client, tmp_path)

    assert rc == 0
    out = capsys.readouterr().out
    assert "Dynamic-exit decision: EXIT" in out
    assert "EXIT PENDING HUMAN CONFIRMATION" in out
    assert "confirm_pending_order.py" in out
    positions = stores["position_store"].load()
    assert len(positions) == 1
    assert positions[0].exit_pending_order_id is not None
    assert len(sdk.orders.create_calls) == 1  # the entry only -- awaiting_approval never reaches place_order


# --- EXIT eligible, auto_exit_enabled=True -> real exit closes the position --

def test_evaluator_exit_with_auto_exit_enabled_closes_the_real_position(tmp_path, monkeypatch, capsys):
    slug = "one-shot-exit-auto-confirmed"
    _patch_coinbase_fake_candles(monkeypatch)
    _patch_assess_btc_market(monkeypatch, MomentumState.REVERSING, signal_count=DEFAULT_MIN_WEAKENING_SIGNALS_FOR_EXIT)
    now = _real_now()
    event = _event(slug=slug, start=now - timedelta(minutes=1), end=now + timedelta(minutes=10), market_slug=slug)
    orders = _FakeOrders(
        preview_response={"order": {"id": "preview-ok"}},
        create_response=[{"id": "ord-entry-2", "executions": []}, {"id": "ord-exit-2", "executions": []}],
        retrieve_responses={
            "ord-entry-2": _order_response("ORDER_STATE_FILLED", quantity=10, cum=10, avg_px="0.50", order_id="ord-entry-2"),
            "ord-exit-2": _order_response("ORDER_STATE_FILLED", quantity=10, cum=10, avg_px="0.60", order_id="ord-exit-2"),
        },
    )
    sdk = _FakeSDKClient(
        events=_FakeEvents({slug: {"event": event}}), markets=_FakeMarkets(books={slug: _book_bid_060_ask_062()}),
        orders=orders, account=_FakeAccount(response={"balances": [{"currency": "USD", "currentBalance": 100.0}]}),
    )
    settings = _settings(slug, POLYMARKET_AUTO_EXIT_ENABLED="true")
    assert settings.live_auto_execute is False
    assert settings.auto_exit_enabled is True
    client = PolymarketUSClient(settings, sdk_client=sdk)

    rc, stores = _run_one_shot(settings, client, tmp_path)

    assert rc == 0
    out = capsys.readouterr().out
    assert "Dynamic-exit decision: EXIT" in out
    assert "POSITION CLOSED" in out
    assert stores["position_store"].load() == []
    assert len(orders.create_calls) == 2  # exactly one entry + one exit, never more


# --- BTC feed unreachable: abort safely via the natural HOLD path, not a crash

def test_coinbase_unreachable_degrades_to_insufficient_data_hold_not_a_crash(tmp_path, monkeypatch, capsys):
    slug = "one-shot-feed-unreachable"
    _patch_coinbase_unreachable(monkeypatch)  # no persisted history either -> bars stays empty
    sdk = _sdk_with_entry_fill(slug)
    settings = _settings(slug, POLYMARKET_BTC_PRICE_HISTORY_FILE=str(tmp_path / "btc_history.json"))
    client = PolymarketUSClient(settings, sdk_client=sdk)

    rc, stores = _run_one_shot(settings, client, tmp_path)

    assert rc == 0
    out = capsys.readouterr().out
    assert "Coinbase unreachable" in out
    assert "Dynamic-exit decision: HOLD" in out
    assert "insufficient" in out.lower()
    assert len(stores["position_store"].load()) == 1  # the real entry stands; nothing crashed, nothing forced


# --- Order book fetch failure after a confirmed fill: abort, touch nothing ---

def test_order_book_failure_after_fill_aborts_without_touching_the_position(tmp_path, monkeypatch, capsys):
    slug = "one-shot-book-failure-after-fill"
    _patch_coinbase_fake_candles(monkeypatch)
    sdk = _sdk_with_entry_fill(slug)
    settings = _settings(slug)
    client = PolymarketUSClient(settings, sdk_client=sdk)

    original_get_order_book = PolymarketUSClient.get_order_book
    call_count = {"n": 0}

    def _flaky(self, token_id):
        call_count["n"] += 1
        if call_count["n"] <= 2:
            # The entry phase itself calls get_order_book TWICE: once
            # inside find_active_btc_market() (to populate BinaryMarket.
            # yes_bid/yes_ask), once explicitly in run_manual_test()'s own
            # risk/liquidity check. Let both succeed -- only THIS script's
            # own later fetch, for the exit evaluation, should fail.
            return original_get_order_book(self, token_id)
        raise RuntimeError("simulated transport failure")

    monkeypatch.setattr(PolymarketUSClient, "get_order_book", _flaky)

    rc, stores = _run_one_shot(settings, client, tmp_path)

    assert rc == 1
    out = capsys.readouterr().out
    assert "ABORTING: could not fetch the live order book" in out
    assert "remains OPEN and unaffected" in out
    positions = stores["position_store"].load()
    assert len(positions) == 1
    assert positions[0].condition_id == slug


# --- Runtime order-count guard -------------------------------------------------

def test_order_guard_blocks_a_second_buy_before_it_reaches_the_exchange():
    underlying_calls: list = []
    original = PolymarketUSClient.place_order

    class _FakeOrdersCounter:
        def create(self, params):
            underlying_calls.append(params)
            return {"id": f"ord-{len(underlying_calls)}", "executions": []}

    class _FakeSDK:
        def __init__(self):
            self.orders = _FakeOrdersCounter()

    settings = _settings("guard-test-slug")
    client = PolymarketUSClient(settings, sdk_client=_FakeSDK())
    call_log, restore = one_shot.install_order_guard()
    try:
        from src.polymarket.models import OrderRequest

        order = OrderRequest(
            condition_id="c", token_id="guard-test-slug", outcome="YES", side="BUY", size_usd=5.0, max_price=0.60,
            close_time=_real_now() + timedelta(minutes=5), reason="test",
        )
        client.place_order(order)  # first BUY: allowed
        assert len(underlying_calls) == 1
        with pytest.raises(one_shot.OrderGuardViolation):
            client.place_order(order)  # second BUY: must be refused BEFORE reaching the exchange
        assert len(underlying_calls) == 1  # never reached the fake exchange a second time
        assert call_log == ["BUY"]
    finally:
        restore()
        assert PolymarketUSClient.place_order is original
