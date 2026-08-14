"""Persisted ledger of positions THIS SYSTEM opened via simulated (paper)
entries.

Robinhood has no knowledge of these — they are never real orders (see
src/execution/gateway.py), so there is nothing to "sync" for them from
get_option_positions. This store is their only record, and — like
risk/store.py — it exists because there is no long-running process here:
each ~5-minute cycle is a fresh invocation that needs to rediscover "what
positions is the bot currently watching" from disk.

For positions that DO exist in the real Robinhood account (opened by the
user, outside this bot), see hood_sync.py instead — those are read
directly from get_option_positions on every cycle, never written here.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.position_manager.models import OpenPosition


class PaperPositionStoreError(RuntimeError):
    """Raised when the persisted paper-position ledger can't be trusted.
    Fails closed (like risk/store.py) rather than silently starting over
    with zero tracked positions, which would orphan real simulated trades
    from the system's own awareness of them."""


class PaperPositionStore:
    def __init__(self, path: Path):
        self._path = path

    def load(self) -> list[OpenPosition]:
        if not self._path.is_file():
            return []
        raw = self._path.read_text()
        if not raw.strip():
            return []
        try:
            rows = json.loads(raw)
            return [OpenPosition.from_dict(row) for row in rows]
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PaperPositionStoreError(f"Paper position ledger is corrupted or unreadable: {exc}") from exc

    def save(self, positions: list[OpenPosition]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps([p.to_dict() for p in positions], indent=2, sort_keys=True))

    def add_position(self, position: OpenPosition) -> None:
        positions = self.load()
        if any(p.option_id == position.option_id for p in positions):
            raise PaperPositionStoreError(
                f"A paper position for {position.option_id} already exists — "
                "remove it first or this would silently duplicate the ledger entry"
            )
        positions.append(position)
        self.save(positions)

    def remove_position(self, option_id: str) -> None:
        positions = self.load()
        remaining = [p for p in positions if p.option_id != option_id]
        if len(remaining) == len(positions):
            raise PaperPositionStoreError(f"No paper position found for {option_id} to remove")
        self.save(remaining)
