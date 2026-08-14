"""Tracks which real (Robinhood-synced) option positions THIS SYSTEM itself
opened via a confirmed live order, as opposed to positions the user opened
manually outside this system.

Why this exists: in live mode there is no separate "paper ledger" the way
there is in paper mode — a live entry only becomes a tracked position once
a human approves it and it actually fills, at which point it shows up like
any other holding via hood_sync.py's read from get_option_positions. That
read can't distinguish "the bot opened this" from "the user opened this
directly in the Robinhood app" on its own.

That distinction matters for exit proposals: this system should only ever
propose (pending-approval, never automatic) an exit order for a position it
itself opened. It must never start proposing to close a position the user
holds for reasons of their own that this bot knows nothing about, just
because that position happens to also match the exit-evaluator's criteria.
A human can still always act on ANY position through the tools directly —
this store only bounds what the *bot* is allowed to suggest, not what a
human can do.

Same JSON-file, fail-closed convention as the other stores in this
codebase (risk/store.py, position_manager/store.py, pending.py).
"""

from __future__ import annotations

import json
from pathlib import Path


class LiveBotPositionsStoreError(RuntimeError):
    """Raised when the persisted bot-live-positions ledger can't be
    trusted. Fails closed — better to under-propose exits for a position
    that's actually the bot's own than to silently forget the distinction
    and start proposing exits for positions the user opened themselves."""


class LiveBotPositionsStore:
    def __init__(self, path: Path):
        self._path = path

    def load(self) -> set[str]:
        if not self._path.is_file():
            return set()
        raw = self._path.read_text()
        if not raw.strip():
            return set()
        try:
            rows = json.loads(raw)
            if not isinstance(rows, list):
                raise ValueError("expected a JSON list of option_id strings")
            return {str(r) for r in rows}
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise LiveBotPositionsStoreError(f"Bot-live-positions ledger is corrupted or unreadable: {exc}") from exc

    def save(self, option_ids: set[str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(sorted(option_ids), indent=2))

    def add(self, option_id: str) -> None:
        ids = self.load()
        ids.add(option_id)
        self.save(ids)

    def remove(self, option_id: str) -> None:
        ids = self.load()
        ids.discard(option_id)
        self.save(ids)

    def contains(self, option_id: str) -> bool:
        return option_id in self.load()
