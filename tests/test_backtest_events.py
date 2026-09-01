"""Tests for the event queue: chronological ordering, tie-break priority,
and the mechanical LookAheadViolationError guard."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.backtesting.events import EventQueue, FillEvent, LookAheadViolationError, MarketEvent, OrderEvent, PortfolioUpdateEvent, SignalEvent
from src.data.bar import Bar


def _market_event(ts: datetime, symbol="AAPL") -> MarketEvent:
    bar = Bar(timestamp=ts, symbol=symbol, timeframe="day", open=1, high=2, low=0.5, close=1.5, volume=10)
    return MarketEvent(timestamp=ts, symbol=symbol, bar=bar)


def test_events_pop_in_chronological_order():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 3, tzinfo=timezone.utc)
    queue = EventQueue()
    queue.push(_market_event(t2))
    queue.push(_market_event(t0))
    queue.push(_market_event(t1))

    popped = [queue.pop().timestamp for _ in range(3)]
    assert popped == [t0, t1, t2]


def test_same_timestamp_ties_break_by_event_type_priority():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    queue = EventQueue()
    queue.push(PortfolioUpdateEvent(timestamp=t, cash=0, equity=0, positions_value=0, drawdown_pct=0))
    queue.push(_market_event(t))
    queue.push(SignalEvent(timestamp=t, symbol="AAPL", direction="LONG", strength=1.0, strategy_name="s"))

    first = queue.pop()
    second = queue.pop()
    third = queue.pop()
    assert isinstance(first, MarketEvent)
    assert isinstance(second, SignalEvent)
    assert isinstance(third, PortfolioUpdateEvent)


def test_pushing_an_event_before_the_last_popped_timestamp_raises():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    queue = EventQueue()
    queue.push(_market_event(t1))
    queue.pop()  # _last_popped_timestamp is now t1

    with pytest.raises(LookAheadViolationError):
        queue.push(_market_event(t0))  # t0 < t1 — a "past" event after time moved forward


def test_pushing_an_event_at_or_after_last_popped_timestamp_is_fine():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    queue = EventQueue()
    queue.push(_market_event(t0))
    queue.pop()
    queue.push(_market_event(t0))  # same timestamp — allowed
    queue.push(_market_event(t1))  # later — allowed
    assert len(queue) == 2


def test_order_event_rejects_execute_before_generated():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t_earlier = datetime(2025, 12, 31, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="cannot be before"):
        OrderEvent(
            order_id="x", timestamp=t_earlier, generated_at_timestamp=t0, symbol="AAPL", side="buy",
            quantity=1, order_type="market", limit_price=None, strategy_name="s", reason="", risk_decision="APPROVED", risk_reason="",
        )


def test_order_event_rejects_invalid_side_and_quantity():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        OrderEvent(order_id="x", timestamp=t, generated_at_timestamp=t, symbol="AAPL", side="hold", quantity=1, order_type="market", limit_price=None, strategy_name="s", reason="", risk_decision="APPROVED", risk_reason="")
    with pytest.raises(ValueError):
        OrderEvent(order_id="x", timestamp=t, generated_at_timestamp=t, symbol="AAPL", side="buy", quantity=0, order_type="market", limit_price=None, strategy_name="s", reason="", risk_decision="APPROVED", risk_reason="")


def test_empty_queue_is_falsy_and_len_zero():
    queue = EventQueue()
    assert not queue
    assert len(queue) == 0


def test_pushing_unknown_event_type_raises():
    queue = EventQueue()
    with pytest.raises(TypeError):
        queue.push(object())
