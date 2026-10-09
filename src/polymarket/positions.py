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
    # The three fields below back exit_retry_guard.py's bounded
    # retry/cooldown gate (a live incident: EXIT -> UNKNOWN -> EXPIRED ->
    # EXIT -> UNKNOWN -> EXPIRED -> EXIT, repeating with zero cooldown
    # and no check that anything had changed). All three are persisted
    # here, on the position itself, rather than in a separate store —
    # restart-safe by the same construction as exit_pending_order_id,
    # and naturally keyed to this exact position since one already
    # exists by the time an exit is ever considered (unlike the entry
    # side's retry guard, which has no position yet to attach to).
    #
    # pending_exit_edge_points: the EdgeAssessment.btc_points reading
    # (exit_manager.compute_edge_assessment) that justified the
    # CURRENTLY in-flight exit named by exit_pending_order_id above —
    # captured the instant that exit is submitted, so it's still
    # available later, in a possibly different cycle or after a
    # restart, when that attempt's outcome is finally learned. None
    # whenever exit_pending_order_id is None.
    pending_exit_edge_points: float | None = None
    # last_exit_attempt_at / last_exit_attempt_edge_points: when the
    # most recent exit attempt for this position resolved to an
    # authoritative, NO-FILL terminal outcome (expired/rejected/failed
    # — never a genuine fill, and never the non-authoritative "unknown"
    # status), and the pending_exit_edge_points value that attempt was
    # submitted under. Both None whenever there is no such recently-
    # failed attempt to rate-limit a retry against. Cleared back to
    # None the moment any later exit for this position fills (even
    # partially) — a successful fill means there is nothing left to
    # retry-guard against.
    last_exit_attempt_at: datetime | None = None
    last_exit_attempt_edge_points: float | None = None

    @property
    def filled_size_usd(self) -> float:
        return self.filled_shares * self.avg_fill_price

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["opened_at"] = self.opened_at.isoformat()
        d["close_time"] = self.close_time.isoformat()
        d["last_exit_attempt_at"] = self.last_exit_attempt_at.isoformat() if self.last_exit_attempt_at else None
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
            pending_exit_edge_points=data.get("pending_exit_edge_points"),
            last_exit_attempt_at=(
                datetime.fromisoformat(data["last_exit_attempt_at"]) if data.get("last_exit_attempt_at") else None
            ),
            last_exit_attempt_edge_points=data.get("last_exit_attempt_edge_points"),
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
