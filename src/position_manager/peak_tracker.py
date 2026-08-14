"""Persisted peak-price tracking for the dynamic/trailing exit engine (see
evaluator.py's trailing-exit check).

Deliberately NOT a field on OpenPosition: real (Robinhood-synced) positions
are rebuilt fresh from the broker every cycle (see hood_sync.py) — there is
no natural place on that path to carry state forward. A small, dedicated
JSON store keyed by option_id works uniformly for both paper and real
positions, and needs no changes to OpenPosition's shape or persistence.

Same fail-closed convention as the other stores in this codebase: a
corrupted file raises rather than silently resetting every position's peak
back to its entry price, which would quietly disarm trailing protection for
every open position on the very next cycle.
"""

from __future__ import annotations

import json
from pathlib import Path


class PeakPriceStoreError(RuntimeError):
    """Raised when the persisted peak-price ledger can't be trusted."""


class PeakPriceStore:
    def __init__(self, path: Path):
        self._path = path

    def load(self) -> dict[str, float]:
        if not self._path.is_file():
            return {}
        raw = self._path.read_text()
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("expected a JSON object of option_id -> peak price")
            return {str(k): float(v) for k, v in data.items()}
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PeakPriceStoreError(f"Peak-price ledger is corrupted or unreadable: {exc}") from exc

    def save(self, peaks: dict[str, float]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(peaks, indent=2, sort_keys=True))

    def get(self, option_id: str, default: float) -> float:
        return self.load().get(option_id, default)

    def update_peak(self, option_id: str, observed_price: float, floor: float) -> float:
        """Records `observed_price` as the new peak for `option_id` if it's
        higher than what's stored (or higher than `floor`, e.g. the
        position's entry price, when nothing is stored yet). Returns the
        resulting peak — the value callers should actually use this cycle,
        whether or not it changed."""
        peaks = self.load()
        current = peaks.get(option_id, floor)
        new_peak = max(current, observed_price, floor)
        if new_peak != current:
            peaks[option_id] = new_peak
            self.save(peaks)
        return new_peak

    def remove(self, option_id: str) -> None:
        peaks = self.load()
        if option_id in peaks:
            del peaks[option_id]
            self.save(peaks)
