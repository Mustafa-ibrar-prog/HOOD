"""Open-position tracking. Base scope is "buy and hold to resolution" —
a 15-minute binary market settles automatically at close (the YES or
NO token you hold pays $1/share if it won, $0 if it didn't) — see
engine.py's settle_resolved_positions(), still the fallback whenever a
position's profit target is never reached.

Selling back into the order book BEFORE resolution — an early,
automatic profit-target exit — is implemented in exit_manager.py.
`exit_pending_order_id` below is that module's own idempotency guard:
while set, a position has an exit order in flight (or of genuinely
unknown outcome) and must never be offered a second one.

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
    # Actual entry commission/fee, in USD, when the API reported one for
    # the entry fill (see us_client.get_fill_status's fee_usd) — 0.0
    # means "none reported," consistent with FillResult.fee_usd being
    # None in that case (there is no ambiguity to preserve here the way
    # there is on the exit side, since exit_manager.py's net-P&L
    # computation is the only place that must distinguish "no fee
    # reported" from "zero fee" — see its docstring).
    entry_fee_usd: float = 0.0
    # Set by exit_manager.py the instant a profit-target exit order is
    # submitted (the PendingLiveOrder.id of that exit), and cleared only
    # once that exit is authoritatively reconciled (fully filled, not
    # filled, or the position's filled_shares has been reduced by a
    # partial fill and a fresh exit becomes eligible again). This is the
    # idempotency guard that keeps check_and_execute_profit_target_exits()
    # from ever submitting a second exit order for the same position
    # while one is already in flight or of unknown outcome — restart-safe
    # because it is persisted here, not held in memory.
    exit_pending_order_id: str | None = None

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
            entry_fee_usd=float(data.get("entry_fee_usd", 0.0)),
            exit_pending_order_id=data.get("exit_pending_order_id"),
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

    def get(self, client_order_id: str) -> OpenPosition | None:
        for position in self.load():
            if position.client_order_id == client_order_id:
                return position
        return None

    def update(self, position: OpenPosition) -> None:
        """Replaces the existing entry matching `position.client_order_id`
        in place (same identity key add_if_absent/exists/get use) —
        exit_manager.py's only way to record a partial exit fill's
        reduced filled_shares, or to set/clear exit_pending_order_id,
        without going through remove()+add_if_absent() (which would
        briefly make the position vanish from the ledger between the
        two calls, and would refuse the re-add since add_if_absent is
        itself an idempotency guard keyed on this same client_order_id)."""
        positions = self.load()
        for i, existing in enumerate(positions):
            if existing.client_order_id == position.client_order_id:
                positions[i] = position
                self.save(positions)
                return
        raise PolymarketPositionStoreError(
            f"No position with client_order_id={position.client_order_id!r} to update — it was never added"
        )
