"""File-backed pending-order ledger — mirrors src/execution/pending.py's
PendingOrderStore exactly: fails closed on a corrupted file (raises,
never silently resets to an empty ledger, which could let a stale
pending order be forgotten and re-proposed)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.polymarket.models import PendingLiveOrder


class PolymarketPendingOrderStoreError(RuntimeError):
    pass


class PolymarketPendingOrderStore:
    def __init__(self, path: Path):
        self._path = path

    def load(self) -> list[PendingLiveOrder]:
        if not self._path.is_file():
            return []
        raw = self._path.read_text()
        if not raw.strip():
            return []
        try:
            rows = json.loads(raw)
            return [PendingLiveOrder.from_dict(row) for row in rows]
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PolymarketPendingOrderStoreError(f"Pending-order ledger is corrupted or unreadable: {exc}") from exc

    def save(self, orders: list[PendingLiveOrder]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps([o.to_dict() for o in orders], indent=2, sort_keys=True))

    def add(self, pending: PendingLiveOrder) -> None:
        orders = self.load()
        orders.append(pending)
        self.save(orders)

    def get(self, pending_order_id: str) -> PendingLiveOrder | None:
        for order in self.load():
            if order.id == pending_order_id:
                return order
        return None

    def update(self, pending: PendingLiveOrder) -> None:
        orders = self.load()
        for i, existing in enumerate(orders):
            if existing.id == pending.id:
                orders[i] = pending
                self.save(orders)
                return
        raise PolymarketPendingOrderStoreError(f"No pending order {pending.id!r} to update — it was never added")

    def list_awaiting_approval(self, now: datetime | None = None) -> list[PendingLiveOrder]:
        """The single, actionable definition of "a pending order that
        still needs a human decision": status == "awaiting_approval" AND
        not yet expired. A record that's still marked awaiting_approval
        but whose expires_at has passed is NOT actionable -- it's
        history, left behind because nothing happened to swept it yet.

        Normalizes any such stale record to the terminal "expired"
        status FIRST, via the existing expire_stale() state transition
        (persisted to the ledger, never silently dropped), so a caller
        asking "is there anything I need to act on" never has to
        separately reason about expiry itself, and the ledger reflects
        reality on every call, not just after an explicit sweep."""
        now = now or datetime.now(timezone.utc)
        self.expire_stale(now)
        return [o for o in self.load() if o.status == "awaiting_approval"]

    def expire_stale(self, now: datetime) -> list[PendingLiveOrder]:
        orders = self.load()
        expired: list[PendingLiveOrder] = []
        for i, order in enumerate(orders):
            if order.status == "awaiting_approval" and now >= order.expires_at:
                updated = order.with_status("expired", decided_at=now, decided_by="system:expiry")
                orders[i] = updated
                expired.append(updated)
        if expired:
            self.save(orders)
        return expired
