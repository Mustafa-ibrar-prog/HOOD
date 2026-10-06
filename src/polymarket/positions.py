"""Open-position tracking. v1 scope is deliberately "buy and hold to
resolution" — a 15-minute binary market settles automatically at close
(the YES or NO token you hold pays $1/share if it won, $0 if it
didn't), so there is no options-style stop-loss/take-profit exit to
build for a first version. Selling back into the order book before
resolution (an early exit) is a real Polymarket feature and a natural
v2, not built here — see engine.py's settle_resolved_positions()."""

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
    condition_id: str
    token_id: str
    outcome: str  # "YES" or "NO"
    entry_price: float
    size_usd: float
    shares: float
    opened_at: datetime
    close_time: datetime

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["opened_at"] = self.opened_at.isoformat()
        d["close_time"] = self.close_time.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OpenPosition":
        return cls(
            condition_id=data["condition_id"], token_id=data["token_id"], outcome=data["outcome"],
            entry_price=float(data["entry_price"]), size_usd=float(data["size_usd"]), shares=float(data["shares"]),
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

    def add(self, position: OpenPosition) -> None:
        positions = self.load()
        positions.append(position)
        self.save(positions)

    def remove(self, condition_id: str) -> None:
        positions = [p for p in self.load() if p.condition_id != condition_id]
        self.save(positions)
