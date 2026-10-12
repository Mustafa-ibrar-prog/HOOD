"""Persisted daily risk state — mirrors src/risk/store.py's
DailyRiskState exactly in spirit: no long-running process should trust
in-memory counters across restarts, and a corrupted file must fail
closed (raise) rather than silently reset to zero trades / zero daily
loss, which would quietly bypass the daily loss cap."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path


class PolymarketRiskStateError(RuntimeError):
    pass


@dataclass
class DailyPnlState:
    trade_date: date
    trades_opened: int = 0
    realized_pnl_usd: float = 0.0
    open_position_count: int = 0
    last_exit_time: str | None = None  # ISO timestamp, for the cooldown check

    def to_json(self) -> str:
        data = asdict(self)
        data["trade_date"] = self.trade_date.isoformat()
        return json.dumps(data, indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> "DailyPnlState":
        try:
            data = json.loads(raw)
            return cls(
                trade_date=date.fromisoformat(data["trade_date"]),
                trades_opened=int(data["trades_opened"]),
                realized_pnl_usd=float(data["realized_pnl_usd"]),
                open_position_count=int(data.get("open_position_count", 0)),
                last_exit_time=data.get("last_exit_time"),
            )
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PolymarketRiskStateError(f"Daily P&L state file is corrupted or unreadable: {exc}") from exc


class DailyPnlStateStore:
    def __init__(self, path: Path):
        self._path = path

    def load(self, *, today: date | None = None) -> DailyPnlState:
        """A missing file, or one from a previous UTC day, both return a
        FRESH state for `today` — never raise just because a new trading
        day started. A file that exists, is for today, but is corrupted
        DOES raise (fail closed)."""
        today = today or datetime.now(timezone.utc).date()
        if not self._path.is_file():
            return DailyPnlState(trade_date=today)
        raw = self._path.read_text()
        if not raw.strip():
            return DailyPnlState(trade_date=today)
        state = DailyPnlState.from_json(raw)
        if state.trade_date != today:
            return DailyPnlState(trade_date=today)
        return state

    def save(self, state: DailyPnlState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(state.to_json())
