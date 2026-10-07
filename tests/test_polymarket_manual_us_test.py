"""Tests for scripts/manual_polymarket_us_test.py's testable core
(run_manual_test) -- the ONE-TIME MANUAL LIVE TEST for Polymarket US
(see that script's module docstring for the full flow/safety-gate
list).

Reuses the fake-SDK boundary objects and fixture builders already
established in tests/test_polymarket_us_client.py (_FakeSDKClient,
_FakeEvents, _FakeMarkets, _FakeOrders, _event, _book_level,
_book_response, _order_response, _settings) rather than duplicating
them -- this file only adds what's specific to exercising
run_manual_test's own gate logic (amount cap, emergency stop, the
live-mode switches, preview success/failure, submission-vs-fill,
duplicate reconciliation).

IMPORTANT: run_manual_test's risk checks (DATA_FRESHNESS, ENTRY_CUTOFF)
read BinaryMarket.data_age_seconds / seconds_to_close, which are both
computed against the REAL wall clock (datetime.now(timezone.utc)), not
against any `now` passed in. So every fixture below anchors its
start/end times to the real wall clock at test-run time (`_real_now()`),
never to a fixed historical date.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from scripts.manual_polymarket_us_test import main, run_manual_test  # noqa: E402
from src.execution.emergency_stop import EmergencyStopStore  # noqa: E402
from src.polymarket import reconciliation  # noqa: E402
from src.polymarket.logger import PolymarketDecisionLogger  # noqa: E402
from src.polymarket.models import OrderRequest, PendingLiveOrder  # noqa: E402
from src.polymarket.pending import PolymarketPendingOrderStore  # noqa: E402
from src.polymarket.positions import OpenPosition, PolymarketPositionStore  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402
from src.polymarket.state import DailyPnlStateStore  # noqa: E402
from src.polymarket.us_client import PolymarketUSClient  # noqa: E402
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


_LIVE_CREDS = {"POLYMARKET_US_KEY_ID": "test-key-id", "POLYMARKET_US_SECRET_KEY": "dGVzdC1zZWNyZXQ="}


def _settings(slug: str, **overrides) -> PolymarketSettings:
    env = {"POLYMARKET_VENUE": "us", "POLYMARKET_US_MARKET_SLUG": slug}
    env.update(overrides)
    return PolymarketSettings.from_env(env=env)


def _good_book() -> dict:
    # bid/ask within POLYMARKET_MAX_SPREAD_PCT's 5% default, and enough
    # size at/below a 0.60 max_price to clear the $25 default
    # POLYMARKET_MIN_ORDER_BOOK_LIQUIDITY_USD.
    return _book_response([_book_level("0.54", 100)], [_book_level("0.55", 100)])


def _happy_event(slug: str) -> dict:
    now = _real_now()
    return _event(slug=slug, start=now - timedelta(minutes=1), end=now + timedelta(minutes=10), market_slug=slug)


def _happy_sdk(slug: str, *, orders: _FakeOrders | None = None) -> _FakeSDKClient:
    return _FakeSDKClient(
        events=_FakeEvents({slug: {"event": _happy_event(slug)}}),
        markets=_FakeMarkets(books={slug: _good_book()}),
        orders=orders or _FakeOrders(preview_response={"order": {"id": "preview-ok"}}),
        account=_FakeAccount(response={"balances": [{"currency": "USD", "currentBalance": 51.58}]}),
    )


def _stores(tmp_path) -> dict:
    return dict(
        decision_logger=PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False),
        state_store=DailyPnlStateStore(tmp_path / "pnl.json"),
        position_store=PolymarketPositionStore(tmp_path / "positions.json"),
        pending_store=PolymarketPendingOrderStore(tmp_path / "pending.json"),
        emergency_stop_store=EmergencyStopStore(tmp_path / "estop.json"),
    )


def _stores_with_emergency_stop_cleared(tmp_path) -> dict:
    """EmergencyStopStore fails closed: with no persisted record at
    all, is_stopped() defaults to True (STOPPED) -- see
    emergency_stop.py's _DEFAULT_STATE. Tests that need to reach past
    the emergency-stop gate (to exercise preview/submission/
    reconciliation behavior) must explicitly clear it first, exactly
    like a real human operator would have to."""
    stores = _stores(tmp_path)
    stores["emergency_stop_store"].clear(authorized_by="user:test-harness", reason="test setup")
    return stores


def _run(settings, client, stores, *, outcome="YES", amount=5.0, max_price=0.60, confirm_live=False, now=None):
    return run_manual_test(
        settings=settings, client=client, outcome=outcome, amount=amount, max_price=max_price,
        confirm_live=confirm_live, now=now, **stores,
    )


# --- Paper mode (the default) -----------------------------------------------

def test_paper_mode_default_opens_a_position_from_a_simulated_fill(tmp_path, capsys):
    slug = "manual-test-market-1"
    sdk = _happy_sdk(slug)
    client = PolymarketUSClient(_settings(slug), sdk_client=sdk)
    stores = _stores(tmp_path)

    rc = _run(_settings(slug), client, stores)

    assert rc == 0
    assert stores["position_store"].load()[0].condition_id == slug
    assert "PAPER FILL" in capsys.readouterr().out


def test_confirm_live_in_paper_mode_is_still_only_a_paper_dry_run(tmp_path, capsys):
    """--confirm-live is a LIVE-mode-only concept: in paper mode
    (POLYMARKET_TRADING_MODE=paper) it is simply ignored, and the exact
    same paper pipeline runs regardless, ending in a simulated fill --
    never a real order."""
    slug = "manual-test-market-2"
    sdk = _happy_sdk(slug)
    client = PolymarketUSClient(_settings(slug), sdk_client=sdk)
    stores = _stores(tmp_path)

    rc = _run(_settings(slug), client, stores, confirm_live=True)

    assert rc == 0
    out = capsys.readouterr().out
    assert "PAPER FILL" in out
    assert sdk.orders.create_calls == []  # never actually submitted anywhere


# --- Gate 5: amount vs POLYMARKET_MAX_BET_USD --------------------------------

def test_amount_over_max_bet_is_refused_before_any_market_lookup(tmp_path, capsys):
    slug = "manual-test-market-3"
    sdk = _FakeSDKClient()  # deliberately empty -- must never be consulted
    client = PolymarketUSClient(_settings(slug, POLYMARKET_MAX_BET_USD="5.0"), sdk_client=sdk)
    stores = _stores(tmp_path)

    rc = _run(_settings(slug, POLYMARKET_MAX_BET_USD="5.0"), client, stores, amount=100.0)

    assert rc == 1
    assert "exceeds the configured" in capsys.readouterr().out
    assert stores["pending_store"].load() == []


# --- Manual-override market resolution failures (reject, don't crash) ------

def test_missing_market_is_refused_cleanly(tmp_path, capsys):
    slug = "does-not-exist-anywhere"
    sdk = _FakeSDKClient()  # no event, no market registered under this slug
    client = PolymarketUSClient(_settings(slug), sdk_client=sdk)
    stores = _stores(tmp_path)

    rc = _run(_settings(slug), client, stores)

    assert rc == 1
    assert "could not retrieve the exact market" in capsys.readouterr().out


def test_mismatched_slug_is_refused_cleanly(tmp_path, capsys):
    slug = "manual-test-market-mismatch"
    now = _real_now()
    wrong = _event(slug="something-else-entirely", start=now - timedelta(minutes=1), end=now + timedelta(minutes=10))
    sdk = _FakeSDKClient(events=_FakeEvents({slug: {"event": wrong}}))
    client = PolymarketUSClient(_settings(slug), sdk_client=sdk)
    stores = _stores(tmp_path)

    rc = _run(_settings(slug), client, stores)

    assert rc == 1
    assert "could not retrieve the exact market" in capsys.readouterr().out


def test_inactive_market_is_refused_cleanly(tmp_path, capsys):
    slug = "manual-test-market-inactive"
    now = _real_now()
    inactive = _event(slug=slug, start=now - timedelta(minutes=1), end=now + timedelta(minutes=10),
                       market_slug=slug, active=False, closed=True)
    sdk = _FakeSDKClient(events=_FakeEvents({slug: {"event": inactive}}))
    client = PolymarketUSClient(_settings(slug), sdk_client=sdk)
    stores = _stores(tmp_path)

    rc = _run(_settings(slug), client, stores)

    assert rc == 1
    assert "could not retrieve the exact market" in capsys.readouterr().out


# --- Risk checks still apply in the manual-override path --------------------

def test_insufficient_liquidity_is_refused_by_risk_checks(tmp_path, capsys):
    slug = "manual-test-market-illiquid"
    now = _real_now()
    event = _event(slug=slug, start=now - timedelta(minutes=1), end=now + timedelta(minutes=10), market_slug=slug)
    thin_book = _book_response([_book_level("0.54", 1)], [_book_level("0.55", 1)])  # $0.55 total, well under $25
    sdk = _FakeSDKClient(events=_FakeEvents({slug: {"event": event}}), markets=_FakeMarkets(books={slug: thin_book}))
    client = PolymarketUSClient(_settings(slug), sdk_client=sdk)
    stores = _stores(tmp_path)

    rc = _run(_settings(slug), client, stores)

    assert rc == 1
    out = capsys.readouterr().out
    assert "ORDER_BOOK_LIQUIDITY" in out
    assert "risk checks did not pass" in out
    assert stores["position_store"].load() == []


# --- No manual override set => existing BTC 15m discovery path untouched ---

def test_no_slug_set_falls_through_to_btc_15m_discovery(tmp_path, capsys):
    """Deliberately does NOT assert rc==0 / a position being opened --
    the real current 15-minute window's remaining time (and thus
    ENTRY_CUTOFF) is a function of the wall clock at the moment this
    test happens to run, which this test must not be sensitive to. The
    one property under test is that, with POLYMARKET_US_MARKET_SLUG
    unset, run_manual_test resolves the market via the real BTC 15m
    deterministic-slug discovery path (client._current_window/
    _expected_event_slug) rather than the manual-override path or a
    "could not retrieve the exact market" failure."""
    now = _real_now()
    settings_no_slug = PolymarketSettings.from_env(env={"POLYMARKET_VENUE": "us"})
    client = PolymarketUSClient(settings_no_slug)
    window_start, window_end = client._current_window(now)
    btc_slug = client._expected_event_slug(window_start)
    event = _event(slug=btc_slug, start=window_start, end=window_end, market_slug=btc_slug, title="BTC Up or Down 15m")
    sdk = _FakeSDKClient(events=_FakeEvents({btc_slug: {"event": event}}), markets=_FakeMarkets(books={btc_slug: _good_book()}))
    client = PolymarketUSClient(settings_no_slug, sdk_client=sdk)
    stores = _stores(tmp_path)

    _run(settings_no_slug, client, stores)

    assert f"slug:      {btc_slug}" in capsys.readouterr().out


# --- Live mode: every gate is independently required ------------------------

def test_live_without_confirm_live_flag_stops_after_a_ready_preflight(tmp_path, capsys):
    """Gate 3 missing: every other gate is satisfied (a READY
    preflight), but --confirm-live was not passed -- must stop cleanly
    with no submission at all (not even a pending order created),
    return 0 (this is an expected, clean stop, not a failure)."""
    slug = "manual-test-live-1"
    sdk = _happy_sdk(slug)
    settings = _settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true",
    )
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores_with_emergency_stop_cleared(tmp_path)

    rc = _run(settings, client, stores, confirm_live=False)

    assert rc == 0
    out = capsys.readouterr().out
    assert "READY FOR FIRST $5 LIVE TEST: YES" in out
    assert "Preflight PASSED" in out
    assert sdk.orders.create_calls == []
    assert stores["position_store"].load() == []
    assert stores["pending_store"].load() == []  # preflight-only must never create a pending order


def test_live_trading_not_confirmed_is_refused_even_with_confirm_live(tmp_path, capsys):
    """Gate 1/2 missing: POLYMARKET_TRADING_MODE=live but
    POLYMARKET_LIVE_TRADING_CONFIRMED is NOT true -- LivePolymarketGateway
    itself refuses to construct; must surface as a clean REFUSING
    message, never an unhandled traceback."""
    slug = "manual-test-live-2"
    sdk = _happy_sdk(slug)
    settings = _settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="false",
    )
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores(tmp_path)

    rc = _run(settings, client, stores, confirm_live=True)

    assert rc == 1
    out = capsys.readouterr().out
    assert "READY FOR FIRST $5 LIVE TEST: NO" in out
    assert "POLYMARKET_LIVE_TRADING_CONFIRMED is not true" in out
    assert sdk.orders.create_calls == []


def test_emergency_stop_active_refuses_a_live_attempt(tmp_path, capsys):
    slug = "manual-test-live-3"
    sdk = _happy_sdk(slug)
    settings = _settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true",
    )
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores(tmp_path)
    stores["emergency_stop_store"].activate(reason="test", set_by="system:test")

    rc = _run(settings, client, stores, confirm_live=True)

    assert rc == 1
    out = capsys.readouterr().out
    assert "READY FOR FIRST $5 LIVE TEST: NO" in out
    assert "EMERGENCY STOP: active" in out
    assert sdk.orders.create_calls == []


def test_preview_failure_refuses_a_live_attempt(tmp_path, capsys):
    """Gate 6: orders.preview() failing must block a live submission,
    even though every other gate is satisfied."""
    slug = "manual-test-live-4"
    sdk = _happy_sdk(slug, orders=_FakeOrders(preview_exc=RuntimeError("preview endpoint is down")))
    settings = _settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true",
    )
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores_with_emergency_stop_cleared(tmp_path)

    rc = _run(settings, client, stores, confirm_live=True)

    assert rc == 1
    assert "orders.preview() did not succeed" in capsys.readouterr().out
    assert sdk.orders.create_calls == []


# --- Live happy path: submission reaches the exchange, then reconciles -----

def test_live_submission_that_fills_opens_a_position(tmp_path, capsys):
    """Order submission != fill determination: place_order()'s own
    response is ignored for fill purposes; only the separate
    reconcile_order() -> get_fill_status() lookup decides whether a
    position opens."""
    slug = "manual-test-live-5"
    orders = _FakeOrders(
        preview_response={"order": {"id": "preview-ok"}},
        create_response={"id": "ord-live-5", "executions": []},
        retrieve_responses={"ord-live-5": _order_response("ORDER_STATE_FILLED", quantity=8, cum=8, avg_px="0.55")},
    )
    sdk = _happy_sdk(slug, orders=orders)
    settings = _settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true",
    )
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores_with_emergency_stop_cleared(tmp_path)

    rc = _run(settings, client, stores, confirm_live=True)

    assert rc == 0
    out = capsys.readouterr().out
    assert "SUBMISSION: submitted" in out
    assert "POSITION CREATED: YES" in out
    positions = stores["position_store"].load()
    assert len(positions) == 1
    assert positions[0].condition_id == slug


def test_live_submission_that_does_not_fill_opens_no_position(tmp_path, capsys):
    slug = "manual-test-live-6"
    orders = _FakeOrders(
        preview_response={"order": {"id": "preview-ok"}},
        create_response={"id": "ord-live-6", "executions": []},
        retrieve_responses={"ord-live-6": _order_response("ORDER_STATE_REJECTED", quantity=8, cum=0)},
    )
    sdk = _happy_sdk(slug, orders=orders)
    settings = _settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true",
    )
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores_with_emergency_stop_cleared(tmp_path)

    rc = _run(settings, client, stores, confirm_live=True)

    assert rc == 0
    assert "POSITION CREATED: NO" in capsys.readouterr().out
    assert stores["position_store"].load() == []


def test_duplicate_reconciliation_does_not_double_create_a_position(tmp_path):
    """Calling reconcile_order() a second time for the same pending
    order (e.g. a restart-safety sweep picking up the same order this
    script already reconciled) must be a no-op, per
    reconciliation.py's own idempotency guard."""
    slug = "manual-test-live-7"
    orders = _FakeOrders(
        preview_response={"order": {"id": "preview-ok"}},
        create_response={"id": "ord-live-7", "executions": []},
        retrieve_responses={"ord-live-7": _order_response("ORDER_STATE_FILLED", quantity=8, cum=8, avg_px="0.55")},
    )
    sdk = _happy_sdk(slug, orders=orders)
    settings = _settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true",
    )
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores_with_emergency_stop_cleared(tmp_path)

    rc = _run(settings, client, stores, confirm_live=True)
    assert rc == 0
    assert len(stores["position_store"].load()) == 1

    pending = stores["pending_store"].load()[0]
    second = reconciliation.reconcile_order(
        pending, client=client, pending_store=stores["pending_store"], position_store=stores["position_store"],
        state_store=stores["state_store"], decision_logger=stores["decision_logger"],
    )

    assert second is None  # already reconciled -- no-op
    assert len(stores["position_store"].load()) == 1


# --- main()'s argparse-level gates ------------------------------------------

def test_bad_outcome_is_rejected_by_argparse(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "manual_polymarket_us_test.py", "--market-slug", "whatever", "--outcome", "MAYBE",
        "--amount", "5", "--max-price", "0.6",
    ])
    with pytest.raises(SystemExit):
        main()


def test_live_existing_open_position_blocks_the_preflight(tmp_path, capsys):
    """Gate 8: an existing open position must block a new live attempt
    -- this is a one-position integration test, never an
    averaging-down tool."""
    slug = "manual-test-live-positions"
    sdk = _happy_sdk(slug)
    settings = _settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true",
    )
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores_with_emergency_stop_cleared(tmp_path)
    stores["position_store"].add_if_absent(OpenPosition(
        condition_id="some-other-market", token_id="some-other-market", outcome="YES",
        requested_size_usd=5.0, filled_shares=8.0, avg_fill_price=0.55, order_id="ord-prior",
        client_order_id="prior-1", status="filled", opened_at=_real_now(), close_time=_real_now(),
    ))

    rc = _run(settings, client, stores, confirm_live=True)

    assert rc == 1
    out = capsys.readouterr().out
    assert "READY FOR FIRST $5 LIVE TEST: NO" in out
    assert "OPEN POSITIONS: 1 existing open position" in out
    assert sdk.orders.create_calls == []


def test_live_existing_pending_order_blocks_the_preflight(tmp_path, capsys):
    """Gate 9: a pending order already awaiting approval must block a
    new live attempt -- refuses to risk a duplicate/conflicting
    submission."""
    slug = "manual-test-live-pending"
    sdk = _happy_sdk(slug)
    settings = _settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true",
    )
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores_with_emergency_stop_cleared(tmp_path)
    prior_order = OrderRequest(
        condition_id="some-other-market", token_id="some-other-market", outcome="YES", side="BUY",
        size_usd=5.0, max_price=0.55, close_time=_real_now() + timedelta(minutes=5), reason="prior test",
    )
    stores["pending_store"].add(PendingLiveOrder.new(order=prior_order, expiry_seconds=600))

    rc = _run(settings, client, stores, confirm_live=True)

    assert rc == 1
    out = capsys.readouterr().out
    assert "READY FOR FIRST $5 LIVE TEST: NO" in out
    assert "PENDING ORDERS: 1 pending order" in out
    assert sdk.orders.create_calls == []


def test_live_wide_spread_and_thin_liquidity_reaches_the_preflight_and_names_both_gates(tmp_path, capsys):
    """Regression for the real live scenario reported: best_bid=0.06
    best_ask=0.07 (15.4% spread, over the 5% default limit) and thin
    ask-side liquidity (well under the $25 default minimum). This must
    NOT short-circuit on the early risk-check message -- it must flow
    all the way into the consolidated LIVE PREFLIGHT block (so AUTH/
    BALANCE/discovery/order-book are still shown), land on READY: NO,
    and name BOTH failing risk checks individually in the STOP
    reasons, not a generic "see above" pointer. No order attempted."""
    slug = "manual-test-live-wide-spread"
    thin_book = _book_response([_book_level("0.06", 50)], [_book_level("0.07", 300)])  # $21 of ask liquidity
    sdk = _happy_sdk(slug)
    sdk.markets.books[slug] = thin_book
    settings = _settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true",
    )
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores_with_emergency_stop_cleared(tmp_path)

    rc = _run(settings, client, stores, confirm_live=True, max_price=0.08)

    assert rc == 1
    out = capsys.readouterr().out
    # Still reaches the full preflight -- this is the fix: a failed risk
    # check must not pre-empt the consolidated status.
    assert "LIVE PREFLIGHT" in out
    assert "AUTH: OK" in out
    assert "READY FOR FIRST $5 LIVE TEST: NO" in out
    assert "STOP. The following gate(s) are not satisfied:" in out
    assert "RISK:MAX_SPREAD" in out
    assert "RISK:ORDER_BOOK_LIQUIDITY" in out
    assert sdk.orders.create_calls == []
    assert stores["pending_store"].load() == []  # no pending order created either


def test_automatic_rollover_to_the_next_window_fetches_a_fresh_order_book(tmp_path, capsys):
    """Points 3/10: with no --market-slug, each invocation re-resolves
    the CURRENT window via automatic discovery and fetches a FRESH
    order book for it -- never a cached/stale one from a previous
    window. Simulates two consecutive 15-minute windows with
    DIFFERENT order books and confirms each run reflects its own."""
    window_1 = datetime(2026, 10, 7, 21, 45, tzinfo=timezone.utc)
    window_2 = datetime(2026, 10, 7, 22, 0, tzinfo=timezone.utc)
    slug_1 = f"btc-updown-15m-{window_1:%Y-%m-%d-%H%M}z"
    slug_2 = f"btc-updown-15m-{window_2:%Y-%m-%d-%H%M}z"
    event_1 = _event(slug=slug_1, start=window_1, end=window_1 + timedelta(minutes=15), market_slug=slug_1)
    event_2 = _event(slug=slug_2, start=window_2, end=window_2 + timedelta(minutes=15), market_slug=slug_2)
    book_1 = _book_response([_book_level("0.54", 100)], [_book_level("0.55", 100)])  # tight, liquid
    book_2 = _book_response([_book_level("0.06", 50)], [_book_level("0.07", 300)])  # wide, thin
    sdk = _FakeSDKClient(
        events=_FakeEvents({slug_1: {"event": event_1}, slug_2: {"event": event_2}}),
        markets=_FakeMarkets(books={slug_1: book_1, slug_2: book_2}),
        orders=_FakeOrders(preview_response={"order": {"id": "preview-ok"}}),
        account=_FakeAccount(response={"balances": [{"currency": "USD", "currentBalance": 51.58}]}),
    )
    settings_no_slug = PolymarketSettings.from_env(env={
        "POLYMARKET_VENUE": "us", **_LIVE_CREDS,
        "POLYMARKET_TRADING_MODE": "live", "POLYMARKET_LIVE_TRADING_CONFIRMED": "true",
    })
    client = PolymarketUSClient(settings_no_slug, sdk_client=sdk)
    stores = _stores_with_emergency_stop_cleared(tmp_path)

    _run(settings_no_slug, client, stores, confirm_live=False, now=window_1 + timedelta(minutes=2))
    out_1 = capsys.readouterr().out
    assert f"EVENT SLUG: {slug_1}" in out_1
    assert "BEST BID: 0.54" in out_1

    _run(settings_no_slug, client, stores, confirm_live=False, now=window_2 + timedelta(minutes=2))
    out_2 = capsys.readouterr().out
    assert f"EVENT SLUG: {slug_2}" in out_2
    assert "BEST BID: 0.06" in out_2  # the SECOND window's own book, not the first's cached one


def test_live_unknown_fill_status_stops_and_does_not_assume_a_fill(tmp_path, capsys):
    """If get_fill_status() can't confidently interpret the exchange's
    response, this must STOP and report it, never assume a fill either
    way, and never submit a second order automatically."""
    slug = "manual-test-live-unknown-fill"
    orders = _FakeOrders(
        preview_response={"order": {"id": "preview-ok"}},
        create_response={"id": "ord-live-unknown", "executions": []},
        retrieve_responses={"ord-live-unknown": _order_response("ORDER_STATE_SOMETHING_NEW_WE_DONT_KNOW", quantity=8, cum=0)},
    )
    sdk = _happy_sdk(slug, orders=orders)
    settings = _settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true",
    )
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores_with_emergency_stop_cleared(tmp_path)

    rc = _run(settings, client, stores, confirm_live=True)

    assert rc == 1
    out = capsys.readouterr().out
    assert "FILL STATUS: unknown" in out
    assert "do not assume a fill" in out
    assert stores["position_store"].load() == []
    assert len(sdk.orders.create_calls) == 1  # exactly one submission attempt -- no automatic retry/second order


def test_live_mode_with_no_market_slug_uses_automatic_btc_discovery(tmp_path, capsys):
    """--market-slug is optional: with POLYMARKET_US_MARKET_SLUG unset,
    even in live mode, the preflight resolves the market via the real
    automatic BTC 15m discovery path -- a production live test must
    never require pasting a fresh slug every 15 minutes.

    Deliberately asserts on the EVENT SLUG: line (printed right after
    discovery, before risk checks run) rather than on reaching the full
    LIVE PREFLIGHT block or any particular risk outcome -- the real
    current window's remaining time (ENTRY_CUTOFF) is a function of the
    wall clock at the moment this test happens to run, which this test
    must not be sensitive to."""
    now = _real_now()
    settings_no_slug = PolymarketSettings.from_env(env={
        "POLYMARKET_VENUE": "us", **_LIVE_CREDS,
        "POLYMARKET_TRADING_MODE": "live", "POLYMARKET_LIVE_TRADING_CONFIRMED": "true",
    })
    client = PolymarketUSClient(settings_no_slug)
    window_start, window_end = client._current_window(now)
    btc_slug = client._expected_event_slug(window_start)
    event = _event(slug=btc_slug, start=window_start, end=window_end, market_slug=btc_slug, title="BTC Up or Down 15m")
    sdk = _FakeSDKClient(
        events=_FakeEvents({btc_slug: {"event": event}}), markets=_FakeMarkets(books={btc_slug: _good_book()}),
        orders=_FakeOrders(preview_response={"order": {"id": "preview-ok"}}),
        account=_FakeAccount(response={"balances": [{"currency": "USD", "currentBalance": 51.58}]}),
    )
    client = PolymarketUSClient(settings_no_slug, sdk_client=sdk)
    stores = _stores_with_emergency_stop_cleared(tmp_path)

    _run(settings_no_slug, client, stores, confirm_live=False)

    out = capsys.readouterr().out
    assert f"EVENT SLUG: {btc_slug}" in out
    assert f"TRADEABLE MARKET SLUG: {btc_slug}" in out


def test_non_us_venue_is_refused(monkeypatch, tmp_path, capsys):
    """main() itself (not run_manual_test) must refuse to proceed when
    POLYMARKET_VENUE isn't "us" -- this script only ever makes sense
    against the US venue's manual-override mechanism."""
    monkeypatch.setattr(sys, "argv", [
        "manual_polymarket_us_test.py", "--market-slug", "whatever", "--outcome", "YES",
        "--amount", "5", "--max-price", "0.6",
    ])
    monkeypatch.setenv("POLYMARKET_VENUE", "international")
    # main() itself writes os.environ["POLYMARKET_US_MARKET_SLUG"] directly
    # (the same mechanism verify_polymarket_setup.py --market-slug uses) --
    # pre-registering it with monkeypatch here ensures that mutation is
    # still cleaned up after this test, even though monkeypatch didn't
    # perform it directly.
    monkeypatch.setenv("POLYMARKET_US_MARKET_SLUG", "placeholder")
    monkeypatch.chdir(tmp_path)  # no .env file here to accidentally override POLYMARKET_VENUE
    rc = main()
    assert rc == 1
    assert "Polymarket US only" in capsys.readouterr().out
