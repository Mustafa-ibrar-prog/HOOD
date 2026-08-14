"""The pending-approval record at the heart of "live execution, gated on
per-trade approval."

A PendingLiveOrder is created by LiveExecutionGateway.submit_order() and is
the ONLY thing that method ever does — no order tool is called there. It
sits in PendingOrderStore (a JSON file, same fail-closed convention as
risk/store.py and position_manager/store.py) until one of:

  - a human explicitly approves it, and the orchestrating agent calls
    LiveExecutionGateway.confirm_and_place() with this record's id — the
    only method in this codebase permitted to call place_option_order.
  - a human explicitly rejects it (LiveExecutionGateway.reject_pending()).
  - it expires (PENDING_ORDER_EXPIRY_MINUTES after creation) without a
    decision — confirm_and_place() refuses a stale pending order rather
    than placing it against an order-book that's moved on.

Nothing here ever transitions a record to "placed" except a real call to
place_option_order having actually returned — see gateway.py.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from src.execution.orders import OrderRequest

_STATUSES = frozenset({"awaiting_approval", "approved", "rejected", "expired", "placed", "failed"})


class PendingOrderStoreError(RuntimeError):
    """Raised when the persisted pending-order ledger can't be trusted.
    Fails closed rather than silently starting over with an empty ledger,
    which could let a stale pending order be forgotten and re-proposed."""


@dataclass(frozen=True)
class PendingLiveOrder:
    id: str
    order: OrderRequest
    status: str  # one of _STATUSES
    created_at: datetime
    expires_at: datetime
    decision_context: Mapping[str, Any] = field(default_factory=dict)
    review: Mapping[str, Any] | None = None  # raw review_option_order response, if captured
    decided_at: datetime | None = None
    decided_by: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"status must be one of {sorted(_STATUSES)}, got {self.status!r}")

    @classmethod
    def new(
        cls,
        *,
        order: OrderRequest,
        expiry_minutes: int,
        decision_context: Mapping[str, Any] | None = None,
        review: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> "PendingLiveOrder":
        now = now or datetime.now(timezone.utc)
        return cls(
            id=str(uuid.uuid4()),
            order=order,
            status="awaiting_approval",
            created_at=now,
            expires_at=now + timedelta(minutes=expiry_minutes),
            decision_context=dict(decision_context or {}),
            review=review,
        )

    def with_status(
        self,
        status: str,
        *,
        decided_at: datetime | None = None,
        decided_by: str | None = None,
        error: str | None = None,
    ) -> "PendingLiveOrder":
        return replace(
            self,
            status=status,
            decided_at=decided_at if decided_at is not None else self.decided_at,
            decided_by=decided_by if decided_by is not None else self.decided_by,
            error=error if error is not None else self.error,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "order": self.order.to_dict(),
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "decision_context": dict(self.decision_context),
            "review": dict(self.review) if self.review is not None else None,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "decided_by": self.decided_by,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PendingLiveOrder":
        return cls(
            id=data["id"],
            order=OrderRequest.from_dict(data["order"]),
            status=data["status"],
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
            decision_context=dict(data.get("decision_context") or {}),
            review=dict(data["review"]) if data.get("review") is not None else None,
            decided_at=datetime.fromisoformat(data["decided_at"]) if data.get("decided_at") else None,
            decided_by=data.get("decided_by"),
            error=data.get("error"),
        )


class PendingOrderStore:
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
            raise PendingOrderStoreError(f"Pending-order ledger is corrupted or unreadable: {exc}") from exc

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
        raise PendingOrderStoreError(f"No pending order {pending.id!r} to update — it was never added")

    def list_awaiting_approval(self) -> list[PendingLiveOrder]:
        return [o for o in self.load() if o.status == "awaiting_approval"]

    def expire_stale(self, now: datetime) -> list[PendingLiveOrder]:
        """Marks every still-awaiting-approval order past its expiry as
        "expired" and persists the change. Returns the ones just expired.
        Does not raise — expiry is routine housekeeping, not a failure."""
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
