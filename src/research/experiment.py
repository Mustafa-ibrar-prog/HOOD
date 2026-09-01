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

Phase 4 additions (section 20-21): `strategy_family`/`classification`/
`oos_metrics`/`cost_sensitivity`/`tags`/`backtest_id`/
`supersedes_experiment_id` — all optional, all additive; every Phase 2
field keeps its exact name, type, and position. `supersedes_experiment_id`
is how a "new version" of a prior experiment stays linked to it WITHOUT
ever overwriting the original record — this store was already append-only
before Phase 4 (record() always appends; nothing here ever edits or
deletes a prior line), so "do not overwrite historical results" was
already the design; supersedes_experiment_id just makes the lineage
between an old and a revised experiment explicit rather than implicit.
ExperimentStore.query() answers the section-20 example questions
("every experiment that tested momentum", "OOS Sharpe above X", "failed
under 2x costs") directly against the stored records.
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
    strategy_family: str | None = None  # e.g. "momentum", "mean_reversion" — enables query(strategy_family=...)
    classification: str | None = None  # StrategyClassification value (src.research.classification)
    oos_metrics: Mapping[str, Any] = field(default_factory=dict)
    cost_sensitivity: Mapping[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    backtest_id: str | None = None  # FK into BacktestResult/BacktestTradeJournal (Phase 3)
    supersedes_experiment_id: str | None = None  # links a revised experiment to the one it replaces, without overwriting it
    hypothesis_id: str | None = None  # FK into HypothesisRegistry (Phase 4) — enables search-space accounting (Phase 5)
    universe_name: str | None = None  # FK into a src.data.universe.Universe's .name
    experiment_fingerprint: str | None = None  # Phase 7, Part 18: a content hash over the dimensions that, if changed, MUST produce a new experiment/version — see src.research.experiment_fingerprint.compute_experiment_fingerprint
    partition_dataset_id: str | None = None  # Phase 7, Part 1: FK into a src.research.partition.ResearchDatasetPartition, when this experiment ran against a formally partitioned dataset
    research_family_id: str | None = None  # Phase 7, Part 2: FK grouping this experiment with others in the same research family for multiple-testing accounting

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
            strategy_family=data.get("strategy_family"),
            classification=data.get("classification"),
            oos_metrics=dict(data.get("oos_metrics", {})),
            cost_sensitivity=dict(data.get("cost_sensitivity", {})),
            tags=tuple(data.get("tags", ())),
            backtest_id=data.get("backtest_id"),
            supersedes_experiment_id=data.get("supersedes_experiment_id"),
            hypothesis_id=data.get("hypothesis_id"),
            universe_name=data.get("universe_name"),
            experiment_fingerprint=data.get("experiment_fingerprint"),
            partition_dataset_id=data.get("partition_dataset_id"),
            research_family_id=data.get("research_family_id"),
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
        strategy_family: str | None = None,
        classification: str | None = None,
        oos_metrics: Mapping[str, Any] | None = None,
        cost_sensitivity: Mapping[str, Any] | None = None,
        tags: Sequence[str] = (),
        backtest_id: str | None = None,
        supersedes_experiment_id: str | None = None,
        hypothesis_id: str | None = None,
        universe_name: str | None = None,
        experiment_fingerprint: str | None = None,
        partition_dataset_id: str | None = None,
        research_family_id: str | None = None,
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
            strategy_family=strategy_family,
            classification=classification,
            oos_metrics=dict(oos_metrics or {}),
            cost_sensitivity=dict(cost_sensitivity or {}),
            tags=tuple(tags),
            backtest_id=backtest_id,
            supersedes_experiment_id=supersedes_experiment_id,
            hypothesis_id=hypothesis_id,
            universe_name=universe_name,
            experiment_fingerprint=experiment_fingerprint,
            partition_dataset_id=partition_dataset_id,
            research_family_id=research_family_id,
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

    def query(
        self,
        *,
        strategy_family: str | None = None,
        classification: str | None = None,
        min_oos_sharpe: float | None = None,
        failed_at_cost_multiplier: float | None = None,
        tag: str | None = None,
        hypothesis_id: str | None = None,
        universe_name: str | None = None,
        research_family_id: str | None = None,
    ) -> list[ExperimentRecord]:
        """Answers the section-20 example questions directly:
          query(strategy_family="momentum")                 -> "every experiment that tested momentum"
          query(min_oos_sharpe=0.5)                          -> "every experiment with OOS Sharpe above X"
          query(failed_at_cost_multiplier=2.0)                -> "experiments that failed under 2x transaction costs"
        Every filter is optional and AND-combined; omit all of them to get
        every record (equivalent to load_all())."""
        records = self.load_all()
        if strategy_family is not None:
            records = [r for r in records if r.strategy_family == strategy_family]
        if classification is not None:
            records = [r for r in records if r.classification == classification]
        if min_oos_sharpe is not None:
            records = [r for r in records if isinstance(r.oos_metrics.get("sharpe_ratio"), (int, float)) and r.oos_metrics["sharpe_ratio"] >= min_oos_sharpe]
        if failed_at_cost_multiplier is not None:
            records = [
                r for r in records
                if any(
                    point.get("cost_multiplier") == failed_at_cost_multiplier and point.get("viable") is False
                    for point in r.cost_sensitivity.get("points", [])
                )
            ]
        if tag is not None:
            records = [r for r in records if tag in r.tags]
        if hypothesis_id is not None:
            records = [r for r in records if r.hypothesis_id == hypothesis_id]
        if universe_name is not None:
            records = [r for r in records if r.universe_name == universe_name]
        if research_family_id is not None:
            records = [r for r in records if r.research_family_id == research_family_id]
        return records
