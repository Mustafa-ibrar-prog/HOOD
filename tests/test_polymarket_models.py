from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.polymarket.models import (
    BinaryMarket,
    BookLevel,
    FillResult,
    OrderBookSnapshot,
    OrderRequest,
    PendingLiveOrder,
    SubmissionOutcome,
    TradeThesis,
)


def _market(**overrides) -> BinaryMarket:
    now = datetime.now(timezone.utc)
    defaults = dict(
        condition_id="cond-1", question="Will BTC be up?", token_id_yes="tok-yes", token_id_no="tok-no",
        close_time=now + timedelta(minutes=10), fetched_at=now, yes_bid=0.45, yes_ask=0.47,
    )
    defaults.update(overrides)
    return BinaryMarket(**defaults)


def _order(**overrides) -> OrderRequest:
    now = datetime.now(timezone.utc)
    defaults = dict(
        condition_id="cond-1", token_id="t", outcome="YES", side="BUY", size_usd=5.0,
        max_price=0.5, close_time=now + timedelta(minutes=10), reason="x",
    )
    defaults.update(overrides)
    return OrderRequest(**defaults)


def _book(**overrides) -> OrderBookSnapshot:
    defaults = dict(
        token_id="t", bids=(BookLevel(price=0.48, size=100.0),), asks=(BookLevel(price=0.50, size=100.0),),
        fetched_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return OrderBookSnapshot(**defaults)


# --- BinaryMarket -------------------------------------------------------------

def test_yes_mid_and_spread():
    market = _market(yes_bid=0.40, yes_ask=0.50)
    assert market.yes_mid == 0.45
    assert market.yes_spread_pct == pytest.approx((0.50 - 0.40) / 0.45, rel=1e-3)


def test_yes_mid_none_without_two_sided_quote():
    market = _market(yes_bid=None, yes_ask=0.5)
    assert market.yes_mid is None
    assert market.yes_spread_pct is None


def test_token_id_for_outcome():
    market = _market()
    assert market.token_id_for("YES") == "tok-yes"
    assert market.token_id_for("NO") == "tok-no"
    with pytest.raises(ValueError):
        market.token_id_for("MAYBE")


def test_data_age_seconds_reflects_real_elapsed_time():
    stale = _market(fetched_at=datetime.now(timezone.utc) - timedelta(seconds=30))
    assert stale.data_age_seconds >= 30


def test_seconds_to_close_counts_down():
    market = _market(close_time=datetime.now(timezone.utc) + timedelta(seconds=60))
    assert 55 < market.seconds_to_close <= 60


def test_trade_thesis_validates_outcome_and_confidence():
    TradeThesis(outcome="YES", catalyst="x", confidence=0.5)
    with pytest.raises(ValueError):
        TradeThesis(outcome="MAYBE", catalyst="x", confidence=0.5)
    with pytest.raises(ValueError):
        TradeThesis(outcome="YES", catalyst="x", confidence=1.5)


# --- OrderBookSnapshot / executable_liquidity_usd (Task 6) -------------------

def test_liquidity_sufficient_when_above_threshold():
    book = _book(asks=(BookLevel(price=0.50, size=100.0),))  # $50 notional at 0.50
    assert book.executable_liquidity_usd(side="BUY", max_price=0.55) == pytest.approx(50.0)


def test_liquidity_insufficient_when_below_threshold():
    book = _book(asks=(BookLevel(price=0.50, size=10.0),))  # only $5 notional
    liquidity = book.executable_liquidity_usd(side="BUY", max_price=0.55)
    assert liquidity == pytest.approx(5.0)
    assert liquidity < 25.0  # below a typical POLYMARKET_MIN_ORDER_BOOK_LIQUIDITY_USD


def test_liquidity_empty_book_is_zero_not_an_error():
    book = _book(asks=())
    assert book.executable_liquidity_usd(side="BUY", max_price=0.99) == 0.0
    assert book.best_ask is None


def test_liquidity_malformed_level_zero_size_contributes_nothing():
    book = _book(asks=(BookLevel(price=0.50, size=0.0),))
    assert book.executable_liquidity_usd(side="BUY", max_price=0.99) == 0.0


def test_liquidity_one_sided_book_sell_side_empty():
    # Only asks present — a SELL (which consumes bids) correctly sees zero.
    book = _book(bids=(), asks=(BookLevel(price=0.50, size=100.0),))
    assert book.executable_liquidity_usd(side="SELL", max_price=0.99) == 0.0
    assert book.executable_liquidity_usd(side="BUY", max_price=0.99) == pytest.approx(50.0)


def test_liquidity_one_sided_book_buy_side_empty():
    book = _book(bids=(BookLevel(price=0.48, size=100.0),), asks=())
    assert book.executable_liquidity_usd(side="BUY", max_price=0.99) == 0.0


def test_liquidity_exactly_at_threshold_counts_as_sufficient():
    # $25.00 notional exactly — a >= comparison in risk.py must treat this as passing.
    book = _book(asks=(BookLevel(price=0.50, size=50.0),))
    assert book.executable_liquidity_usd(side="BUY", max_price=0.55) == pytest.approx(25.0)


def test_liquidity_only_counts_levels_at_or_below_max_price():
    book = _book(asks=(BookLevel(price=0.50, size=100.0), BookLevel(price=0.60, size=100.0)))
    liquidity = book.executable_liquidity_usd(side="BUY", max_price=0.55)
    assert liquidity == pytest.approx(50.0)  # only the 0.50 level counts; the 0.60 level is excluded


def test_liquidity_rejects_invalid_side():
    book = _book()
    with pytest.raises(ValueError):
        book.executable_liquidity_usd(side="HOLD", max_price=0.5)


# --- OrderBookSnapshot.executable_shares (profit-target exit liquidity check) --

def test_executable_shares_sell_side_sums_bids_at_or_above_min_price():
    book = _book(bids=(BookLevel(price=0.45, size=10.0), BookLevel(price=0.40, size=20.0)))
    assert book.executable_shares(side="SELL", min_price=0.45) == pytest.approx(10.0)
    assert book.executable_shares(side="SELL", min_price=0.40) == pytest.approx(30.0)


def test_executable_shares_sell_side_excludes_levels_below_min_price():
    book = _book(bids=(BookLevel(price=0.432, size=5.0), BookLevel(price=0.40, size=100.0)))
    # Only the 0.432 level (at/above a 0.432 target) counts -- the much
    # larger 0.40 level is below the floor and must not count as usable.
    assert book.executable_shares(side="SELL", min_price=0.432) == pytest.approx(5.0)


def test_executable_shares_buy_side_sums_asks_at_or_below_max_price():
    book = _book(asks=(BookLevel(price=0.50, size=10.0), BookLevel(price=0.60, size=20.0)))
    assert book.executable_shares(side="BUY", max_price=0.55) == pytest.approx(10.0)


def test_executable_shares_empty_book_is_zero_not_an_error():
    book = _book(bids=())
    assert book.executable_shares(side="SELL", min_price=0.5) == 0.0


def test_executable_shares_rejects_invalid_side():
    book = _book()
    with pytest.raises(ValueError):
        book.executable_shares(side="HOLD", min_price=0.5)


def test_best_bid_ask_mid_spread():
    book = _book(bids=(BookLevel(price=0.48, size=10),), asks=(BookLevel(price=0.52, size=10),))
    assert book.best_bid == 0.48
    assert book.best_ask == 0.52
    assert book.mid == 0.50
    assert book.spread_pct == pytest.approx(0.08)


def test_data_age_seconds_on_order_book():
    stale = _book(fetched_at=datetime.now(timezone.utc) - timedelta(seconds=15))
    assert stale.data_age_seconds >= 15


# --- OrderRequest --------------------------------------------------------------

def test_order_request_validates_bounds():
    _order(max_price=0.5)
    with pytest.raises(ValueError):
        _order(max_price=1.0)
    with pytest.raises(ValueError):
        _order(size_usd=0)
    with pytest.raises(ValueError):
        _order(outcome="MAYBE")
    with pytest.raises(ValueError):
        _order(order_type="GTC")


def test_order_request_round_trip():
    order = _order(outcome="NO", side="SELL", max_price=0.3, size_usd=10.0, ref_id="r1")
    assert OrderRequest.from_dict(order.to_dict()) == order


def test_order_request_defaults_to_fok():
    assert _order().order_type == "FOK"


# --- OrderRequest.quantity/closes_client_order_id (profit-target exit) --------

def test_order_request_quantity_defaults_to_none_and_round_trips():
    buy = _order()
    assert buy.quantity is None
    assert buy.closes_client_order_id is None
    assert OrderRequest.from_dict(buy.to_dict()) == buy

    exit_order = _order(side="SELL", quantity=5, closes_client_order_id="client-1")
    assert exit_order.quantity == 5
    assert exit_order.closes_client_order_id == "client-1"
    assert OrderRequest.from_dict(exit_order.to_dict()) == exit_order


def test_order_request_rejects_non_positive_quantity():
    with pytest.raises(ValueError):
        _order(side="SELL", quantity=0)
    with pytest.raises(ValueError):
        _order(side="SELL", quantity=-1)


# --- FillResult (Task 3) -------------------------------------------------------

def test_fill_result_is_fill_only_for_filled_statuses():
    filled = FillResult(order_id="o1", status="filled", requested_shares=10.0, filled_shares=10.0, avg_fill_price=0.5)
    assert filled.is_fill

    resting = FillResult(order_id="o1", status="resting", requested_shares=10.0, filled_shares=0.0, avg_fill_price=None)
    assert not resting.is_fill

    unknown = FillResult(order_id="o1", status="unknown", requested_shares=10.0, filled_shares=0.0, avg_fill_price=None)
    assert not unknown.is_fill  # fail-closed: unknown is never treated as a fill


def test_fill_result_fee_usd_defaults_to_none_not_zero():
    """None means "not reported" (requirement: compute NET P&L from the
    ACTUAL fee data available, never fabricate a $0 fee)."""
    fill = FillResult(order_id="o1", status="filled", requested_shares=5.0, filled_shares=5.0, avg_fill_price=0.432)
    assert fill.fee_usd is None

    with_fee = FillResult(
        order_id="o1", status="filled", requested_shares=5.0, filled_shares=5.0, avg_fill_price=0.432, fee_usd=0.02,
    )
    assert with_fee.fee_usd == pytest.approx(0.02)


def test_fill_result_rejects_inconsistent_shares_and_price():
    with pytest.raises(ValueError):
        FillResult(order_id="o1", status="filled", requested_shares=10.0, filled_shares=5.0, avg_fill_price=None)
    with pytest.raises(ValueError):
        FillResult(order_id="o1", status="cancelled", requested_shares=10.0, filled_shares=5.0, avg_fill_price=0.5)


def test_submission_outcome_rejected_has_no_exchange_order_id():
    outcome = SubmissionOutcome(ok=False, exchange_order_id=None, raw_status=None, error_code="fok_not_filled")
    assert outcome.exchange_order_id is None


# --- PendingLiveOrder (Task 3/5) ------------------------------------------------

def test_pending_live_order_lifecycle():
    order = _order()
    pending = PendingLiveOrder.new(order=order, expiry_seconds=60)
    assert pending.status == "awaiting_approval"
    assert pending.fill_reconciled is False
    submitted = pending.with_status(
        "submitted", decided_at=datetime.now(timezone.utc), decided_by="human:test", exchange_order_id="ex-1",
    )
    assert submitted.status == "submitted"
    assert submitted.exchange_order_id == "ex-1"
    assert submitted.fill_reconciled is False  # not reconciled just by submitting
    assert PendingLiveOrder.from_dict(submitted.to_dict()) == submitted


def test_pending_live_order_reconciled_flag_round_trips():
    order = _order()
    pending = PendingLiveOrder.new(order=order, expiry_seconds=60)
    reconciled = pending.with_status(pending.status, fill_reconciled=True)
    assert reconciled.fill_reconciled is True
    assert PendingLiveOrder.from_dict(reconciled.to_dict()).fill_reconciled is True


def test_pending_live_order_rejects_bad_status():
    order = _order()
    with pytest.raises(ValueError):
        PendingLiveOrder(
            id="x", order=order, status="not-a-real-status",
            created_at=datetime.now(timezone.utc), expires_at=datetime.now(timezone.utc),
        )
