"""Phase 30, Part 9/17 — the options-research event model."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.backtesting.events import LookAheadViolationError, MarketEvent
from src.data.bar import Bar
from src.options.research_events import (
    OptionChainEvent,
    OptionContractEvent,
    OptionExitEvent,
    OptionPositionEvent,
    OptionSignalEvent,
    OrderSimulationEvent,
    ResearchEventQueue,
)

T0 = datetime(2026, 1, 1, 9, 30, tzinfo=timezone.utc)
T1 = datetime(2026, 1, 1, 9, 31, tzinfo=timezone.utc)
T2 = datetime(2026, 1, 1, 9, 32, tzinfo=timezone.utc)


def _bar(ts):
    return Bar(timestamp=ts, symbol="AAPL", timeframe="day", open=1.0, high=1.0, low=1.0, close=1.0, volume=1)


def test_order_simulation_event_validates_side():
    with pytest.raises(ValueError):
        OrderSimulationEvent(timestamp=T0, option_id="c1", side="hold", quantity=1, execution_model="buy_at_ask", simulated_price=5.0, status="simulated_fill")


def test_order_simulation_event_validates_status():
    with pytest.raises(ValueError):
        OrderSimulationEvent(timestamp=T0, option_id="c1", side="buy", quantity=1, execution_model="buy_at_ask", simulated_price=5.0, status="bogus")


def test_order_simulation_fill_requires_a_price():
    with pytest.raises(ValueError):
        OrderSimulationEvent(timestamp=T0, option_id="c1", side="buy", quantity=1, execution_model="buy_at_ask", simulated_price=None, status="simulated_fill")


def test_order_simulation_rejection_allows_no_price():
    ev = OrderSimulationEvent(timestamp=T0, option_id="c1", side="buy", quantity=1, execution_model="buy_at_ask", simulated_price=None, status="execution_data_limited", reason="no ask")
    assert ev.simulated_price is None


def test_queue_processes_events_in_priority_order_at_same_timestamp():
    q = ResearchEventQueue()
    exit_ev = OptionExitEvent(timestamp=T0, option_id="c1", exit_reason="profit_target", realized_pnl=100.0)
    market_ev = MarketEvent(timestamp=T0, symbol="AAPL", bar=_bar(T0))
    chain_ev = OptionChainEvent(timestamp=T0, underlying_symbol="AAPL", contract_ids=("c1",))
    q.push(exit_ev)
    q.push(market_ev)
    q.push(chain_ev)
    order = [q.pop() for _ in range(3)]
    assert order == [market_ev, chain_ev, exit_ev]


def test_queue_rejects_out_of_order_push_lookahead():
    q = ResearchEventQueue()
    q.push(OptionContractEvent(timestamp=T1, option_id="c1", field="bid", value=5.0))
    q.pop()
    with pytest.raises(LookAheadViolationError):
        q.push(OptionContractEvent(timestamp=T0, option_id="c1", field="bid", value=5.1))


def test_queue_rejects_unknown_event_type():
    q = ResearchEventQueue()
    with pytest.raises(TypeError):
        q.push(object())


def test_full_chronological_replay_across_all_seven_kinds():
    q = ResearchEventQueue()
    events = [
        MarketEvent(timestamp=T0, symbol="AAPL", bar=_bar(T0)),
        OptionChainEvent(timestamp=T0, underlying_symbol="AAPL", contract_ids=("c1",)),
        OptionContractEvent(timestamp=T0, option_id="c1", field="bid", value=5.0),
        OptionSignalEvent(timestamp=T1, option_id="c1", underlying_symbol="AAPL", signal_strength=0.5, strategy_name="test"),
        OrderSimulationEvent(timestamp=T1, option_id="c1", side="buy", quantity=1, execution_model="buy_at_ask", simulated_price=5.1, status="simulated_fill"),
        OptionPositionEvent(timestamp=T2, option_id="c1", structure="LONG_CALL", market_value=510.0, unrealized_pnl=0.0),
        OptionExitEvent(timestamp=T2, option_id="c1", exit_reason="expiration", realized_pnl=10.0),
    ]
    for e in events:
        q.push(e)
    popped = [q.pop() for _ in range(len(events))]
    timestamps = [getattr(e, "timestamp") for e in popped]
    assert timestamps == sorted(timestamps)
    assert len(q) == 0
    assert bool(q) is False
