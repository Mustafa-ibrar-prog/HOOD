"""Open-position tracking. v1 scope is deliberately "buy and hold to
resolution" — a 15-minute binary market settles automatically at close
(the YES or NO token you hold pays $1/share if it won, $0 if it
didn't), so there is no options-style stop-loss/take-profit exit to
build for a first version. Selling back into the order book before
resolution (an early exit) is a real Polymarket feature and a natural
v2, not built here — see engine.py's settle_resolved_positions().

A position is only ever created from a verified FillResult
(models.FillResult.is_fill) — see reconciliation.py. There is no path
in this codebase from "order submitted" directly to a position.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class PolymarketPositionStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenPosition:
    """Every field is about what ACTUALLY happened, not what was
    requested — `requested_size_usd` is kept alongside the filled
    figures specifically so a partial fill is visible, never silently
    conflated with a full one."""

    condition_id: str
    token_id: str
    outcome: str  # "YES" or "NO"
    requested_size_usd: float
    filled_shares: float  # actual shares received, from a verified FillResult
    avg_fill_price: float  # actual average price paid per share
    order_id: str  # exchange order id ("paper:<client_order_id>" in paper mode — see engine.py)
    client_order_id: str  # this system's own idempotency key (PendingLiveOrder.id, or a generated id in paper mode)
    status: str  # "filled" or "partially_filled" (models.FillStatus) — never anything else
    opened_at: datetime
    close_time: datetime

    @property
    def filled_size_usd(self) -> float:
        return self.filled_shares * self.avg_fill_price

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["opened_at"] = self.opened_at.isoformat()
        d["close_time"] = self.close_time.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OpenPosition":
        return cls(
            condition_id=data["condition_id"], token_id=data["token_id"], outcome=data["outcome"],
            requested_size_usd=float(data["requested_size_usd"]),
            filled_shares=float(data["filled_shares"]), avg_fill_price=float(data["avg_fill_price"]),
            order_id=data["order_id"], client_order_id=data["client_order_id"], status=data["status"],
            opened_at=datetime.fromisoformat(data["opened_at"]), close_time=datetime.fromisoformat(data["close_time"]),
        )


class PolymarketPositionStore:
    def __init__(self, path: Path):
        self._path = path

    def load(self) -> list[OpenPosition]:
        if not self._path.is_file():
            return []
        raw = self._path.read_text()
        if not raw.strip():
            return []
        try:
            return [OpenPosition.from_dict(row) for row in json.loads(raw)]
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PolymarketPositionStoreError(f"Position ledger is corrupted or unreadable: {exc}") from exc

    def save(self, positions: list[OpenPosition]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps([p.to_dict() for p in positions], indent=2, sort_keys=True))

    def exists(self, client_order_id: str) -> bool:
        return any(p.client_order_id == client_order_id for p in self.load())

    def add_if_absent(self, position: OpenPosition) -> bool:
        """The ONLY way this store's contents should grow. Returns False
        (no-op) if a position with this client_order_id already exists
        — the idempotency guarantee reconciliation.py depends on:
        reconciling the same order twice must not create two positions,
        including across a process restart, since this check is based
        on the persisted file, not in-memory state."""
        positions = self.load()
        if any(p.client_order_id == position.client_order_id for p in positions):
            return False
        positions.append(position)
        self.save(positions)
        return True

    def remove(self, condition_id: str) -> None:
        positions = [p for p in self.load() if p.condition_id != condition_id]
        self.save(positions)
