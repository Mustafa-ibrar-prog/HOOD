"""Persisted daily risk state.

There is intentionally no long-running process/timer in this codebase (see
position_manager/monitor.py) — each ~5-minute evaluation is expected to be
triggered externally (e.g. a scheduled Routine). That means counters like
"trades opened today" must survive between separate invocations, so they
live on disk, not in memory.

Safety principle: a corrupted or unreadable state file must FAIL CLOSED
(raise) rather than silently reset to zero trades / zero daily loss, which
would quietly bypass the daily trade and loss limits.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path


class RiskStateError(RuntimeError):
    """Raised when the persisted risk state can't be trusted."""


@dataclass
class DailyRiskState:
    trade_date: date
    trades_opened: int = 0
    realized_pnl_usd: float = 0.0
    unrealized_pnl_usd: float = 0.0
    last_position_size_usd: float | None = None
    last_trade_was_loss: bool = False
    # underlying symbol -> ISO timestamp of most recent exit, for cooldown checks
    last_exit_time_by_symbol: dict[str, str] = field(default_factory=dict)

    @property
    def daily_pnl_usd(self) -> float:
        return self.realized_pnl_usd + self.unrealized_pnl_usd

    def to_json(self) -> str:
        data = asdict(self)
        data["trade_date"] = self.trade_date.isoformat()
        return json.dumps(data, indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> "DailyRiskState":
        try:
            data = json.loads(raw)
            return cls(
                trade_date=date.fromisoformat(data["trade_date"]),
                trades_opened=int(data["trades_opened"]),
                realized_pnl_usd=float(data["realized_pnl_usd"]),
                unrealized_pnl_usd=float(data.get("unrealized_pnl_usd", 0.0)),
                last_position_size_usd=data.get("last_position_size_usd"),
                last_trade_was_loss=bool(data.get("last_trade_was_loss", False)),
                last_exit_time_by_symbol=dict(data.get("last_exit_time_by_symbol", {})),
            )
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RiskStateError(f"Risk state file is corrupted or unreadable: {exc}") from exc

    def last_exit_time(self, symbol: str) -> datetime | None:
        raw = self.last_exit_time_by_symbol.get(symbol)
        return datetime.fromisoformat(raw) if raw else None

    def record_exit(self, symbol: str, at: datetime, realized_pnl_usd: float) -> None:
        self.last_exit_time_by_symbol[symbol] = at.isoformat()
        self.realized_pnl_usd += realized_pnl_usd
        self.last_trade_was_loss = realized_pnl_usd < 0

    def record_trade_opened(self, size_usd: float) -> None:
        self.trades_opened += 1
        self.last_position_size_usd = size_usd


class RiskStateStore:
    """JSON-file-backed persistence for DailyRiskState. Resets to a fresh
    state automatically when the stored trade_date is not today — but only
    on a *successful* read; a file that exists and fails to parse raises
    instead of being treated as "no file" (see RiskStateError above)."""

    def __init__(self, path: Path):
        self._path = path

    def load(self, today: date) -> DailyRiskState:
        if not self._path.is_file():
            return DailyRiskState(trade_date=today)

        raw = self._path.read_text()
        if not raw.strip():
            return DailyRiskState(trade_date=today)

        state = DailyRiskState.from_json(raw)
        if state.trade_date != today:
            return DailyRiskState(trade_date=today)
        return state

    def save(self, state: DailyRiskState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(state.to_json())
