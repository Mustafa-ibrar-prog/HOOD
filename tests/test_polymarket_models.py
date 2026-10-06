from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.polymarket.models import BinaryMarket, OrderRequest, PendingLiveOrder, TradeThesis


def _market(**overrides) -> BinaryMarket:
    now = datetime.now(timezone.utc)
    defaults = dict(
        condition_id="cond-1", question="Will BTC be up?", token_id_yes="tok-yes", token_id_no="tok-no",
        close_time=now + timedelta(minutes=10), fetched_at=now, yes_bid=0.45, yes_ask=0.47,
    )
    defaults.update(overrides)
    return BinaryMarket(**defaults)


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


def test_order_request_validates_bounds():
    OrderRequest(token_id="t", outcome="YES", side="BUY", price=0.5, size_usd=5.0, reason="x")
    with pytest.raises(ValueError):
        OrderRequest(token_id="t", outcome="YES", side="BUY", price=1.0, size_usd=5.0, reason="x")
    with pytest.raises(ValueError):
        OrderRequest(token_id="t", outcome="YES", side="BUY", price=0.5, size_usd=0, reason="x")
    with pytest.raises(ValueError):
        OrderRequest(token_id="t", outcome="MAYBE", side="BUY", price=0.5, size_usd=5.0, reason="x")


def test_order_request_round_trip():
    order = OrderRequest(token_id="t", outcome="NO", side="SELL", price=0.3, size_usd=10.0, reason="x", ref_id="r1")
    assert OrderRequest.from_dict(order.to_dict()) == order


def test_pending_live_order_lifecycle():
    order = OrderRequest(token_id="t", outcome="YES", side="BUY", price=0.5, size_usd=5.0, reason="x")
    pending = PendingLiveOrder.new(order=order, expiry_seconds=60)
    assert pending.status == "awaiting_approval"
    placed = pending.with_status("placed", decided_at=datetime.now(timezone.utc), decided_by="human:test")
    assert placed.status == "placed"
    assert placed.decided_by == "human:test"
    assert PendingLiveOrder.from_dict(placed.to_dict()) == placed


def test_pending_live_order_rejects_bad_status():
    order = OrderRequest(token_id="t", outcome="YES", side="BUY", price=0.5, size_usd=5.0, reason="x")
    with pytest.raises(ValueError):
        PendingLiveOrder(
            id="x", order=order, status="not-a-real-status",
            created_at=datetime.now(timezone.utc), expires_at=datetime.now(timezone.utc),
        )
