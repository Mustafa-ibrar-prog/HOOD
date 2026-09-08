"""Phase 40, Part 17 — the equity curve: one append-only record per
observation cycle, tying every snapshot to the real observation cycle
that supplied its market data (Part 6: "Every paper decision must
identify the observation cycle that supplied its market data")."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.paper_trading.account import PaperExperimentAccountSnapshot


@dataclass(frozen=True)
class EquitySnapshotRecord:
    experiment_id: str
    observation_cycle_id: str
    timestamp: datetime
    cash_usd: float
    market_value_usd: float
    equity_usd: float
    realized_pnl_usd: float
    unrealized_pnl_usd: float
    daily_pnl_usd: float | None  # equity_usd - that day's first snapshot's equity_usd; None for the day's own first snapshot
    cumulative_pnl_usd: float  # equity_usd - starting_cash_usd
    drawdown_pct: float
    peak_equity_usd: float
    open_positions: int
    open_exposure_usd: float  # == market_value_usd, named per Part 17's own vocabulary

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id, "observation_cycle_id": self.observation_cycle_id,
            "timestamp": self.timestamp.isoformat(), "cash_usd": self.cash_usd, "market_value_usd": self.market_value_usd,
            "equity_usd": self.equity_usd, "realized_pnl_usd": self.realized_pnl_usd,
            "unrealized_pnl_usd": self.unrealized_pnl_usd, "daily_pnl_usd": self.daily_pnl_usd,
            "cumulative_pnl_usd": self.cumulative_pnl_usd, "drawdown_pct": self.drawdown_pct,
            "peak_equity_usd": self.peak_equity_usd, "open_positions": self.open_positions,
            "open_exposure_usd": self.open_exposure_usd,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EquitySnapshotRecord":
        return cls(
            experiment_id=data["experiment_id"], observation_cycle_id=data["observation_cycle_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]), cash_usd=data["cash_usd"],
            market_value_usd=data["market_value_usd"], equity_usd=data["equity_usd"],
            realized_pnl_usd=data["realized_pnl_usd"], unrealized_pnl_usd=data["unrealized_pnl_usd"],
            daily_pnl_usd=data.get("daily_pnl_usd"), cumulative_pnl_usd=data["cumulative_pnl_usd"],
            drawdown_pct=data["drawdown_pct"], peak_equity_usd=data["peak_equity_usd"],
            open_positions=data["open_positions"], open_exposure_usd=data["open_exposure_usd"],
        )


def build_equity_snapshot(
    *, experiment_id: str, observation_cycle_id: str, snapshot: PaperExperimentAccountSnapshot,
    first_snapshot_equity_today: float | None,
) -> EquitySnapshotRecord:
    daily_pnl = (snapshot.equity_usd - first_snapshot_equity_today) if first_snapshot_equity_today is not None else None
    return EquitySnapshotRecord(
        experiment_id=experiment_id, observation_cycle_id=observation_cycle_id, timestamp=snapshot.as_of,
        cash_usd=snapshot.cash_usd, market_value_usd=snapshot.open_position_market_value_usd,
        equity_usd=snapshot.equity_usd, realized_pnl_usd=snapshot.realized_pnl_usd,
        unrealized_pnl_usd=snapshot.unrealized_pnl_usd, daily_pnl_usd=daily_pnl,
        cumulative_pnl_usd=round(snapshot.equity_usd - snapshot.starting_cash_usd, 2),
        drawdown_pct=snapshot.current_drawdown_pct, peak_equity_usd=snapshot.peak_equity_usd,
        open_positions=snapshot.open_position_count, open_exposure_usd=snapshot.open_position_market_value_usd,
    )


class EquitySnapshotStore:
    """Append-only JSONL — one row per observation cycle, never
    overwritten (Part 17: "This must create an equity curve")."""

    def __init__(self, path: Path):
        self._path = Path(path)
        self._seen_cycle_ids: set[str] = set()
        if self._path.is_file():
            for line in self._path.read_text().splitlines():
                if line.strip():
                    self._seen_cycle_ids.add(json.loads(line)["observation_cycle_id"])

    def load_all(self) -> list[EquitySnapshotRecord]:
        if not self._path.is_file():
            return []
        return [EquitySnapshotRecord.from_dict(json.loads(line)) for line in self._path.read_text().splitlines() if line.strip()]

    def append(self, record: EquitySnapshotRecord) -> bool:
        """Returns False (no-op) if this observation_cycle_id was already
        recorded — restart-safe, never a duplicate equity-curve point for
        the same real cycle."""
        if record.observation_cycle_id in self._seen_cycle_ids:
            return False
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as fh:
            fh.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
        self._seen_cycle_ids.add(record.observation_cycle_id)
        return True

    def latest(self) -> EquitySnapshotRecord | None:
        rows = self.load_all()
        return rows[-1] if rows else None

    def first_equity_on_date(self, d) -> float | None:
        for row in self.load_all():
            if row.timestamp.date() == d:
                return row.equity_usd
        return None

    def running_peak_equity(self) -> float | None:
        rows = self.load_all()
        return max((r.equity_usd for r in rows), default=None)
