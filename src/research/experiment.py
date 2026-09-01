"""Research experiment tracking: an append-only record of every research
experiment run, so nothing tested is ever forgotten and every result is
traceable back to the exact data/feature/strategy versions that produced
it.

Same append-only-JSONL convention as src/logging/trade_journal.py — a
deliberate parallel: TradeJournal is the permanent record of what the live
system actually did; ExperimentStore is the permanent record of what
research actually tested. Neither is ever read back to auto-mutate
anything — both are for human (and agent) review only.

`experiment_id` is a random UUID (uniqueness only) — REPRODUCIBILITY comes
from `data_version`/`feature_version` instead, which are deterministic
content hashes (src/data/versioning.py): given the same recorded
data_version and feature_version, the exact same dataset and feature
definitions can be reconstructed and the experiment re-run.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ExperimentRecord:
    experiment_id: str
    created_at: datetime
    data_version: str
    feature_version: str
    strategy_version: str | None
    symbols: tuple[str, ...]
    timeframe: str
    prediction_horizon: int | None
    train_period: tuple[str, str] | None
    validation_period: tuple[str, str] | None
    test_period: tuple[str, str] | None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    metrics: Mapping[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExperimentRecord":
        return cls(
            experiment_id=data["experiment_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            data_version=data["data_version"],
            feature_version=data["feature_version"],
            strategy_version=data.get("strategy_version"),
            symbols=tuple(data.get("symbols", ())),
            timeframe=data["timeframe"],
            prediction_horizon=data.get("prediction_horizon"),
            train_period=tuple(data["train_period"]) if data.get("train_period") else None,
            validation_period=tuple(data["validation_period"]) if data.get("validation_period") else None,
            test_period=tuple(data["test_period"]) if data.get("test_period") else None,
            parameters=dict(data.get("parameters", {})),
            metrics=dict(data.get("metrics", {})),
            notes=data.get("notes", ""),
        )


class ExperimentStore:
    def __init__(self, path: Path):
        self._path = path

    def record(
        self,
        *,
        data_version: str,
        feature_version: str,
        symbols: Sequence[str],
        timeframe: str,
        strategy_version: str | None = None,
        prediction_horizon: int | None = None,
        train_period: tuple[str, str] | None = None,
        validation_period: tuple[str, str] | None = None,
        test_period: tuple[str, str] | None = None,
        parameters: Mapping[str, Any] | None = None,
        metrics: Mapping[str, Any] | None = None,
        notes: str = "",
        now: datetime | None = None,
    ) -> ExperimentRecord:
        now = now or datetime.now(timezone.utc)
        record = ExperimentRecord(
            experiment_id=str(uuid.uuid4()),
            created_at=now,
            data_version=data_version,
            feature_version=feature_version,
            strategy_version=strategy_version,
            symbols=tuple(symbols),
            timeframe=timeframe,
            prediction_horizon=prediction_horizon,
            train_period=train_period,
            validation_period=validation_period,
            test_period=test_period,
            parameters=dict(parameters or {}),
            metrics=dict(metrics or {}),
            notes=notes,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(record.to_dict(), sort_keys=True, default=str))
            f.write("\n")
            f.flush()
        return record

    def load_all(self) -> list[ExperimentRecord]:
        if not self._path.is_file():
            return []
        raw = self._path.read_text()
        if not raw.strip():
            return []
        return [ExperimentRecord.from_dict(json.loads(line)) for line in raw.splitlines() if line.strip()]

    def get(self, experiment_id: str) -> ExperimentRecord | None:
        for rec in self.load_all():
            if rec.experiment_id == experiment_id:
                return rec
        return None
