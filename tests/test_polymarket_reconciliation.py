from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.polymarket import reconciliation
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import FillResult, OrderRequest, PendingLiveOrder
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import PolymarketPositionStore
from src.polymarket.state import DailyPnlStateStore


class _FakeClient:
    def __init__(self):
        self._fills: dict[str, FillResult] = {}
        self.get_fill_status_calls: list[str] = []

    def set_fill_result(self, exchange_order_id: str, fill: FillResult) -> None:
        self._fills[exchange_order_id] = fill

    def get_fill_status(self, exchange_order_id: str) -> FillResult:
        self.get_fill_status_calls.append(exchange_order_id)
        return self._fills[exchange_order_id]


def _order(**overrides) -> OrderRequest:
    now = datetime.now(timezone.utc)
    defaults = dict(
        condition_id="cond-1", token_id="tok-yes", outcome="YES", side="BUY", size_usd=5.0,
        max_price=0.55, close_time=now + timedelta(minutes=10), reason="test",
    )
    defaults.update(overrides)
    return OrderRequest(**defaults)


def _harness(tmp_path: Path):
    client = _FakeClient()
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    decision_logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    return client, pending_store, position_store, state_store, decision_logger


def _submitted_pending(pending_store: PolymarketPendingOrderStore, *, exchange_order_id: str, order=None) -> PendingLiveOrder:
    pending = PendingLiveOrder.new(order=order or _order(), expiry_seconds=600)
    pending = pending.with_status("submitted", exchange_order_id=exchange_order_id)
    pending_store.add(pending)
    return pending


# --- reconcile_order: the core fill-determination path (Task 3) -------------

def test_reconcile_order_opens_a_position_on_a_real_fill(tmp_path):
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    pending = _submitted_pending(pending_store, exchange_order_id="ex-1")
    client.set_fill_result("ex-1", FillResult(
        order_id="ex-1", status="filled", requested_shares=10.0, filled_shares=10.0, avg_fill_price=0.5,
    ))

    fill = reconciliation.reconcile_order(
        pending, client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    assert fill is not None and fill.is_fill
    positions = position_store.load()
    assert len(positions) == 1
    assert positions[0].client_order_id == pending.id
    assert positions[0].filled_shares == 10.0
    assert pending_store.get(pending.id).fill_reconciled is True
    state = state_store.load()
    assert state.trades_opened == 1
    assert state.open_position_count == 1


def test_reconcile_order_opens_no_position_on_a_rejection(tmp_path):
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    pending = _submitted_pending(pending_store, exchange_order_id="ex-2")
    client.set_fill_result("ex-2", FillResult(
        order_id="ex-2", status="cancelled", requested_shares=10.0, filled_shares=0.0, avg_fill_price=None,
    ))

    fill = reconciliation.reconcile_order(
        pending, client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    assert fill is not None and not fill.is_fill
    assert position_store.load() == []
    assert pending_store.get(pending.id).fill_reconciled is True


def test_reconcile_order_treats_unknown_status_as_no_fill(tmp_path):
    """Fail-closed (Task 3): an ambiguous/unrecognized exchange response
    must never be treated as a fill. Also NOT marked fill_reconciled --
    unlike a genuine terminal outcome, "unknown" is not an authoritative
    answer (see reconciliation.py's module docstring), so this pending
    order must remain eligible for a later retry."""
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    pending = _submitted_pending(pending_store, exchange_order_id="ex-3")
    client.set_fill_result("ex-3", FillResult(
        order_id="ex-3", status="unknown", requested_shares=10.0, filled_shares=0.0, avg_fill_price=None,
        raw={"lookup_error": "APIConnectionError: timed out"},
    ))

    fill = reconciliation.reconcile_order(
        pending, client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    assert fill is not None and not fill.is_fill
    assert position_store.load() == []
    assert pending_store.get(pending.id).fill_reconciled is False


def test_reconcile_order_unknown_status_is_retried_on_a_later_call(tmp_path):
    """Regression for the real post-submit "unknown" scenario: a first
    lookup attempt fails/is unrecognized (status="unknown"); a LATER
    call for the SAME pending order (e.g. a subsequent
    reconcile_pending_orders() sweep, or a manual re-run after the
    transient problem clears) must actually re-query get_fill_status()
    -- not silently no-op -- and, once the exchange now reports a real
    terminal state, reconcile correctly from there."""
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    pending = _submitted_pending(pending_store, exchange_order_id="ex-unknown")
    client.set_fill_result("ex-unknown", FillResult(
        order_id="ex-unknown", status="unknown", requested_shares=10.0, filled_shares=0.0, avg_fill_price=None,
        raw={"lookup_error": "APIConnectionError: timed out"},
    ))

    first = reconciliation.reconcile_order(
        pending, client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    assert first.status == "unknown"
    assert client.get_fill_status_calls == ["ex-unknown"]

    # The transient problem has since cleared; the exchange now reports
    # a real fill for the SAME order id.
    client.set_fill_result("ex-unknown", FillResult(
        order_id="ex-unknown", status="filled", requested_shares=10.0, filled_shares=10.0, avg_fill_price=0.55,
    ))
    still_pending = pending_store.get(pending.id)
    assert still_pending.fill_reconciled is False  # confirms it was genuinely left re-checkable

    second = reconciliation.reconcile_order(
        still_pending, client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    assert client.get_fill_status_calls == ["ex-unknown", "ex-unknown"]  # genuinely re-queried, not a no-op
    assert second.is_fill
    positions = position_store.load()
    assert len(positions) == 1
    assert positions[0].filled_shares == 10.0
    assert pending_store.get(pending.id).fill_reconciled is True  # now a real terminal answer -- safe to mark done


def test_reconcile_order_handles_a_partial_fill(tmp_path):
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    pending = _submitted_pending(pending_store, exchange_order_id="ex-4")
    client.set_fill_result("ex-4", FillResult(
        order_id="ex-4", status="partially_filled", requested_shares=10.0, filled_shares=4.0, avg_fill_price=0.5,
    ))

    fill = reconciliation.reconcile_order(
        pending, client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    assert fill.is_fill
    positions = position_store.load()
    assert len(positions) == 1
    assert positions[0].filled_shares == 4.0
    assert positions[0].status == "partially_filled"


def test_reconcile_order_returns_none_without_an_exchange_order_id(tmp_path):
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    pending = PendingLiveOrder.new(order=_order(), expiry_seconds=600)  # never submitted
    pending_store.add(pending)

    result = reconciliation.reconcile_order(
        pending, client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    assert result is None
    assert position_store.load() == []


# --- Idempotency (Task 5's explicit requirement) -----------------------------

def test_reconcile_order_is_a_noop_the_second_time(tmp_path):
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    pending = _submitted_pending(pending_store, exchange_order_id="ex-5")
    client.set_fill_result("ex-5", FillResult(
        order_id="ex-5", status="filled", requested_shares=10.0, filled_shares=10.0, avg_fill_price=0.5,
    ))

    first = reconciliation.reconcile_order(
        pending, client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    reconciled_pending = pending_store.get(pending.id)
    second = reconciliation.reconcile_order(
        reconciled_pending, client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    assert first is not None
    assert second is None  # fill_reconciled=True short-circuits immediately
    assert len(position_store.load()) == 1  # still just one position, not two
    state = state_store.load()
    assert state.trades_opened == 1  # not incremented twice


def test_reconcile_order_is_idempotent_across_a_restart(tmp_path):
    """The primary guard (fill_reconciled) persists to disk; a brand-new
    PolymarketPendingOrderStore/PolymarketPositionStore pointed at the
    same files (simulating a fresh process after a crash) must still
    see it and refuse to double-reconcile."""
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    pending = _submitted_pending(pending_store, exchange_order_id="ex-6")
    client.set_fill_result("ex-6", FillResult(
        order_id="ex-6", status="filled", requested_shares=10.0, filled_shares=10.0, avg_fill_price=0.5,
    ))
    reconciliation.reconcile_order(
        pending, client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )

    # Fresh store instances, same files — simulates a restarted process.
    fresh_pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    fresh_position_store = PolymarketPositionStore(tmp_path / "positions.json")
    fresh_state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    fresh_pending = fresh_pending_store.get(pending.id)

    second = reconciliation.reconcile_order(
        fresh_pending, client=client, pending_store=fresh_pending_store, position_store=fresh_position_store,
        state_store=fresh_state_store, decision_logger=decision_logger,
    )
    assert second is None
    assert len(fresh_position_store.load()) == 1


def test_add_if_absent_guard_catches_a_double_reconcile_even_if_the_flag_check_is_skipped(tmp_path):
    """The SECONDARY guard: even if some caller managed to call
    reconcile_order() on a pending order whose fill_reconciled flag
    wasn't checked (or was reset), add_if_absent() in record_fill()
    independently refuses a second position for the same client_order_id."""
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    pending = _submitted_pending(pending_store, exchange_order_id="ex-7")
    fill = FillResult(order_id="ex-7", status="filled", requested_shares=10.0, filled_shares=10.0, avg_fill_price=0.5)
    client.set_fill_result("ex-7", fill)

    first = reconciliation.record_fill(
        fill, pending.order, pending.id, position_store=position_store, state_store=state_store,
        decision_logger=decision_logger, now=datetime.now(timezone.utc),
    )
    second = reconciliation.record_fill(
        fill, pending.order, pending.id, position_store=position_store, state_store=state_store,
        decision_logger=decision_logger, now=datetime.now(timezone.utc),
    )
    assert first is not None
    assert second is None
    assert len(position_store.load()) == 1


# --- reconcile_pending_orders: the restart-safety sweep -----------------------

def test_reconcile_pending_orders_sweeps_every_unreconciled_order(tmp_path):
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    _submitted_pending(pending_store, exchange_order_id="ex-a", order=_order(condition_id="c-a"))
    _submitted_pending(pending_store, exchange_order_id="ex-b", order=_order(condition_id="c-b"))
    client.set_fill_result("ex-a", FillResult(order_id="ex-a", status="filled", requested_shares=10.0, filled_shares=10.0, avg_fill_price=0.5))
    client.set_fill_result("ex-b", FillResult(order_id="ex-b", status="cancelled", requested_shares=10.0, filled_shares=0.0, avg_fill_price=None))

    count = reconciliation.reconcile_pending_orders(
        client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    assert count == 2
    assert len(position_store.load()) == 1  # only the "filled" one opened a position
    assert all(p.fill_reconciled for p in pending_store.load())


def test_reconcile_pending_orders_leaves_an_unknown_result_eligible_for_the_next_sweep(tmp_path):
    """An "unknown" status is attempted (counted) in this sweep, but
    must not be marked fill_reconciled, so the NEXT sweep picks it up
    again automatically -- unlike a genuinely terminal sibling order in
    the same sweep, which is correctly marked done and not retried."""
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    _submitted_pending(pending_store, exchange_order_id="ex-unknown", order=_order(condition_id="c-unknown"))
    _submitted_pending(pending_store, exchange_order_id="ex-filled", order=_order(condition_id="c-filled"))
    client.set_fill_result("ex-unknown", FillResult(order_id="ex-unknown", status="unknown", requested_shares=10.0, filled_shares=0.0, avg_fill_price=None))
    client.set_fill_result("ex-filled", FillResult(order_id="ex-filled", status="filled", requested_shares=10.0, filled_shares=10.0, avg_fill_price=0.5))

    first_sweep = reconciliation.reconcile_pending_orders(
        client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    assert first_sweep == 2  # both attempted
    assert client.get_fill_status_calls == ["ex-unknown", "ex-filled"]
    statuses = {p.order.condition_id: p.fill_reconciled for p in pending_store.load()}
    assert statuses == {"c-unknown": False, "c-filled": True}

    second_sweep = reconciliation.reconcile_pending_orders(
        client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    assert second_sweep == 1  # only the still-unreconciled "unknown" one is attempted again
    assert client.get_fill_status_calls == ["ex-unknown", "ex-filled", "ex-unknown"]


def test_reconcile_pending_orders_skips_already_reconciled_and_never_submitted(tmp_path):
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    never_submitted = PendingLiveOrder.new(order=_order(condition_id="c-never"), expiry_seconds=600)
    pending_store.add(never_submitted)
    already_done = PendingLiveOrder.new(order=_order(condition_id="c-done"), expiry_seconds=600)
    already_done = already_done.with_status("rejected", exchange_order_id=None, fill_reconciled=True)
    pending_store.add(already_done)

    count = reconciliation.reconcile_pending_orders(
        client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    assert count == 0
    assert position_store.load() == []


def test_reconcile_pending_orders_is_safe_to_call_with_an_empty_ledger(tmp_path):
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    count = reconciliation.reconcile_pending_orders(
        client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    assert count == 0


# --- SELL orders are never reconciled by this (BUY-only) sweep --------------
# A live incident's own investigation found that reconcile_pending_orders()
# had no filter on order.side at all -- a live SELL (exit) order that
# reached the exchange and sat unresolved for even one cycle would ALSO
# be swept here and run through record_fill() (the BUY-shaped
# position-creation path), fabricating a bogus "new entry" position out
# of what was actually an exit fill. exit_manager.py's own
# reconcile_exit_fill() is the correct, exclusive owner of SELL
# reconciliation (gated by OpenPosition.exit_pending_order_id, never
# PendingLiveOrder.fill_reconciled).

def test_reconcile_pending_orders_never_touches_a_sell_order(tmp_path):
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    sell_order = _order(condition_id="c-sell", side="SELL", quantity=5)
    _submitted_pending(pending_store, exchange_order_id="ex-sell", order=sell_order)
    # Even if the exchange reports this AS a genuine fill, the generic
    # sweep must never act on it -- a real fill here must come from
    # exit_manager.reconcile_exit_fill() instead.
    client.set_fill_result("ex-sell", FillResult(
        order_id="ex-sell", status="filled", requested_shares=5.0, filled_shares=5.0, avg_fill_price=0.40,
    ))

    count = reconciliation.reconcile_pending_orders(
        client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )

    assert count == 0  # the SELL order was never even attempted
    assert client.get_fill_status_calls == []  # never looked up by this sweep
    assert position_store.load() == []  # no bogus "entry" position fabricated
    sell_pending = [p for p in pending_store.load() if p.order.side == "SELL"][0]
    assert sell_pending.fill_reconciled is False  # untouched -- still exit_manager.py's to reconcile


def test_reconcile_pending_orders_still_reconciles_a_buy_sitting_alongside_a_sell(tmp_path):
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    _submitted_pending(pending_store, exchange_order_id="ex-buy", order=_order(condition_id="c-buy", side="BUY"))
    _submitted_pending(pending_store, exchange_order_id="ex-sell", order=_order(condition_id="c-sell", side="SELL", quantity=5))
    client.set_fill_result("ex-buy", FillResult(
        order_id="ex-buy", status="filled", requested_shares=10.0, filled_shares=10.0, avg_fill_price=0.5,
    ))
    client.set_fill_result("ex-sell", FillResult(
        order_id="ex-sell", status="filled", requested_shares=5.0, filled_shares=5.0, avg_fill_price=0.40,
    ))

    count = reconciliation.reconcile_pending_orders(
        client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )

    assert count == 1  # only the BUY was attempted
    assert client.get_fill_status_calls == ["ex-buy"]
    positions = position_store.load()
    assert len(positions) == 1
    assert positions[0].condition_id == "c-buy"


# --- Stale-entry safety net (see reconciliation.py's own module docstring) --
# A live incident: order D0EEB7H1AZ7J submitted, immediately read back
# "unknown," only adopted FILLED by a later sweep (handled correctly --
# the one-cycle delayed-entry grace already covers this). Separately, an
# even OLDER unresolved entry for the same market resolved FILLED near
# that market's close, reopening a position right after its own
# evidence-driven exit had just closed it. A genuine fill is NEVER
# suppressed (requirement), but it must be visibly flagged when it
# resolves well outside its own decision window.

def test_a_fill_resolved_promptly_is_never_flagged_stale(tmp_path):
    """The common, healthy case: resolves well within both the pending
    record's own expiry AND before its market closes -- no
    stale_entry_fill_adopted log entry at all."""
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    now = datetime.now(timezone.utc)
    order = _order(close_time=now + timedelta(minutes=10))
    pending = PendingLiveOrder.new(order=order, expiry_seconds=60, now=now)
    pending = pending.with_status("submitted", exchange_order_id="ex-fresh")
    pending_store.add(pending)
    client.set_fill_result("ex-fresh", FillResult(
        order_id="ex-fresh", status="filled", requested_shares=10.0, filled_shares=10.0, avg_fill_price=0.5,
    ))

    reconciliation.reconcile_order(
        pending, client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger, now=now + timedelta(seconds=5),
    )

    assert len(position_store.load()) == 1  # still adopted, as always
    stale_entries = [e for e in decision_logger.read_all() if e.get("kind") == "stale_entry_fill_adopted"]
    assert stale_entries == []


def test_a_fill_resolved_after_the_markets_close_time_is_adopted_but_flagged_stale(tmp_path):
    """The exact D0EEB7H1AZ7J-adjacent scenario: the order's OWN market
    has already closed by the time an authoritative fill finally
    arrives. The position IS still created (a real fill is never
    pretended away) but the adoption is flagged distinctly."""
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    now = datetime.now(timezone.utc)
    order = _order(close_time=now - timedelta(minutes=2))  # this order's market already closed
    pending = PendingLiveOrder.new(order=order, expiry_seconds=60, now=now - timedelta(minutes=20))
    pending = pending.with_status("submitted", exchange_order_id="ex-stale-close")
    pending_store.add(pending)
    client.set_fill_result("ex-stale-close", FillResult(
        order_id="ex-stale-close", status="filled", requested_shares=8.0, filled_shares=8.0, avg_fill_price=0.49,
    ))

    fill = reconciliation.reconcile_order(
        pending, client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger, now=now,
    )

    assert fill.is_fill  # the real fill is reconciled correctly, never ignored
    positions = position_store.load()
    assert len(positions) == 1
    assert positions[0].filled_shares == pytest.approx(8.0)
    assert positions[0].avg_fill_price == pytest.approx(0.49)

    stale_entries = [e for e in decision_logger.read_all() if e.get("kind") == "stale_entry_fill_adopted"]
    assert len(stale_entries) == 1
    assert stale_entries[0]["evidence"]["market_closed"] is True


def test_a_fill_resolved_past_its_own_expiry_but_before_close_is_also_flagged_stale(tmp_path):
    """The "old pending entry" scenario: close_time hasn't technically
    arrived yet, but the order sat unresolved far longer than this
    system's own expiry window -- also flagged, independent of
    close_time."""
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    now = datetime.now(timezone.utc)
    order = _order(close_time=now + timedelta(minutes=3))  # still technically open
    pending = PendingLiveOrder.new(order=order, expiry_seconds=60, now=now - timedelta(minutes=10))  # created long ago
    pending = pending.with_status("submitted", exchange_order_id="ex-stale-expiry")
    pending_store.add(pending)
    client.set_fill_result("ex-stale-expiry", FillResult(
        order_id="ex-stale-expiry", status="filled", requested_shares=8.0, filled_shares=8.0, avg_fill_price=0.28,
    ))

    fill = reconciliation.reconcile_order(
        pending, client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger, now=now,
    )

    assert fill.is_fill
    assert len(position_store.load()) == 1  # still adopted -- never pretended away

    stale_entries = [e for e in decision_logger.read_all() if e.get("kind") == "stale_entry_fill_adopted"]
    assert len(stale_entries) == 1
    assert stale_entries[0]["evidence"]["market_closed"] is False
    assert stale_entries[0]["evidence"]["past_expiry"] is True


def test_order_status_unknown_log_preserves_the_raw_diagnostic_detail(tmp_path):
    """A live incident could not determine WHY an order read "unknown"
    from the stored decision log, because the old version of this log
    entry discarded fill.raw (the lookup_error or raw exchange state)
    before writing it. Now preserved verbatim."""
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    pending = _submitted_pending(pending_store, exchange_order_id="ex-diag")
    client.set_fill_result("ex-diag", FillResult(
        order_id="ex-diag", status="unknown", requested_shares=8.0, filled_shares=0.0, avg_fill_price=None,
        raw={"lookup_error": "NotFoundError: order ex-diag not found"},
    ))

    reconciliation.reconcile_order(
        pending, client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )

    entries = [e for e in decision_logger.read_all() if e.get("kind") == "order_status_unknown"]
    assert len(entries) == 1
    assert entries[0]["evidence"]["raw"] == {"lookup_error": "NotFoundError: order ex-diag not found"}
