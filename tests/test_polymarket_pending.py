"""Unit tests for PolymarketPendingOrderStore -- specifically
list_awaiting_approval()'s actionable definition (status ==
"awaiting_approval" AND not yet expired) and its use of the existing
expire_stale() state transition to normalize stale records, never
delete them.

This is the single helper scripts/manual_polymarket_us_test.py and
scripts/one_shot_real_dynamic_exit_test.py both now call instead of
each re-implementing their own "status == awaiting_approval" filter
(the real bug: that naive filter treats a long-expired historical
record as an active conflict)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.polymarket.models import OrderRequest, PendingLiveOrder
from src.polymarket.pending import PolymarketPendingOrderStore


def _order(**overrides) -> OrderRequest:
    defaults = dict(
        condition_id="c", token_id="c", outcome="YES", side="BUY", size_usd=5.0, max_price=0.60,
        close_time=datetime.now(timezone.utc) + timedelta(minutes=10), reason="test",
    )
    defaults.update(overrides)
    return OrderRequest(**defaults)


def _pending(*, expiry_seconds: float, now: datetime | None = None, **overrides) -> PendingLiveOrder:
    return PendingLiveOrder.new(order=_order(**overrides), expiry_seconds=expiry_seconds, now=now)


def test_unexpired_awaiting_approval_is_actionable(tmp_path):
    now = datetime.now(timezone.utc)
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    pending = _pending(expiry_seconds=600, now=now)
    store.add(pending)

    actionable = store.list_awaiting_approval(now)

    assert [p.id for p in actionable] == [pending.id]
    assert store.get(pending.id).status == "awaiting_approval"  # untouched -- still genuinely active


def test_expired_awaiting_approval_is_not_actionable(tmp_path):
    now = datetime.now(timezone.utc)
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    pending = _pending(expiry_seconds=-600, now=now)  # expired 10 minutes before `now`
    store.add(pending)

    actionable = store.list_awaiting_approval(now)

    assert actionable == []


def test_expired_awaiting_approval_is_normalized_not_deleted(tmp_path):
    """Requirement: never manually delete history -- the existing
    expire_stale() state-machine transition flips it to a terminal
    "expired" status, persisted, so the ledger still shows it happened."""
    now = datetime.now(timezone.utc)
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    pending = _pending(expiry_seconds=-600, now=now)
    store.add(pending)

    store.list_awaiting_approval(now)

    all_records = store.load()
    assert len(all_records) == 1  # still present
    assert all_records[0].id == pending.id
    assert all_records[0].status == "expired"
    assert all_records[0].decided_by == "system:expiry"


def test_exactly_at_expiry_boundary_is_not_actionable(tmp_path):
    """now >= expires_at is the expiry condition (matches gateway.py's
    own confirm_and_place() check) -- exactly AT the boundary counts as
    expired, not a edge-case pass-through."""
    now = datetime.now(timezone.utc)
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    pending = PendingLiveOrder.new(order=_order(), expiry_seconds=0, now=now)
    assert pending.expires_at == now

    actionable = store.list_awaiting_approval(now)

    assert actionable == []


def test_submitted_filled_rejected_failed_states_are_never_treated_as_actionable(tmp_path):
    """The existing reconciliation rules already own these terminal/
    in-flight states -- list_awaiting_approval() must not reinterpret
    any of them as "awaiting approval", expired or not."""
    now = datetime.now(timezone.utc)
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    for status in ("submitted", "rejected", "expired", "failed"):
        p = _pending(expiry_seconds=600, now=now)
        p = p.with_status(status, decided_at=now, decided_by="test")
        store.add(p)

    actionable = store.list_awaiting_approval(now)

    assert actionable == []
    # And none of them were touched by the expiry sweep -- expire_stale()
    # only ever transitions records that are THEMSELVES still
    # "awaiting_approval".
    for record in store.load():
        assert record.status in ("submitted", "rejected", "expired", "failed")


def test_mixed_ledger_returns_only_the_genuinely_actionable_ones(tmp_path):
    now = datetime.now(timezone.utc)
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    active = _pending(expiry_seconds=600, now=now)
    expired = _pending(expiry_seconds=-600, now=now)
    filled = _pending(expiry_seconds=600, now=now).with_status("submitted", decided_at=now, decided_by="test")
    store.add(active)
    store.add(expired)
    store.add(filled)

    actionable = store.list_awaiting_approval(now)

    assert [p.id for p in actionable] == [active.id]


def test_list_awaiting_approval_defaults_to_the_real_wall_clock(tmp_path):
    """now is optional -- omitting it must still correctly treat an
    already-expired record (relative to the real clock) as inactionable,
    not require every caller to pass `now` explicitly."""
    store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    expired = _pending(expiry_seconds=-600)
    store.add(expired)

    assert store.list_awaiting_approval() == []
