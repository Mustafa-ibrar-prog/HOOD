from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.polymarket import reconciliation
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import FillResult, OrderRequest, PendingLiveOrder
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import PolymarketPositionStore
from src.polymarket.state import DailyPnlStateStore


class _FakeClient:
    def __init__(self):
        self._fills: dict[str, FillResult] = {}

    def set_fill_result(self, exchange_order_id: str, fill: FillResult) -> None:
        self._fills[exchange_order_id] = fill

    def get_fill_status(self, exchange_order_id: str) -> FillResult:
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
    must never be treated as a fill."""
    client, pending_store, position_store, state_store, decision_logger = _harness(tmp_path)
    pending = _submitted_pending(pending_store, exchange_order_id="ex-3")
    client.set_fill_result("ex-3", FillResult(
        order_id="ex-3", status="unknown", requested_shares=10.0, filled_shares=0.0, avg_fill_price=None,
    ))

    fill = reconciliation.reconcile_order(
        pending, client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    assert fill is not None and not fill.is_fill
    assert position_store.load() == []


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
