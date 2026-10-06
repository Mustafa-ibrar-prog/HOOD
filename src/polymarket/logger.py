"""Structured, append-only JSONL audit trail — same spirit as
src/logging/decision_logger.py (every decision logged, not just trades;
one JSON object per line so partial writes don't corrupt the whole
file), kept as its own small module rather than importing that one's
options-typed methods."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.polymarket.models import OrderResult, PendingLiveOrder
from src.polymarket.risk import RiskDecision


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


class PolymarketDecisionLogger:
    def __init__(self, path: Path, *, also_console: bool = True):
        self._path = path
        self._also_console = also_console

    def _write(self, entry: Mapping[str, Any]) -> None:
        entry = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(_jsonable(entry), sort_keys=True) + "\n")
        if self._also_console:
            print(f"polymarket decision kind={entry.get('kind')}: {entry.get('reason', '')}")

    def log_decision(self, *, kind: str, reason: str, evidence: Mapping[str, Any] | None = None) -> None:
        self._write({"kind": kind, "reason": reason, "evidence": dict(evidence or {})})

    def log_risk_block(self, decision: RiskDecision, *, context: str) -> None:
        self._write({
            "kind": "risk_block", "context": context,
            "reason": "Blocked by risk controls: " + "; ".join(decision.reasons_failed),
            "blocking_reasons": list(decision.reasons_failed),
        })

    def log_simulated_order(self, result: OrderResult) -> None:
        self._write({"kind": "simulated_order", "status": result.status, "order": result.request, "filled_price": result.filled_price})

    def log_pending_order(self, pending: PendingLiveOrder) -> None:
        self._write({"kind": "pending_order", "pending_order": pending})

    def log_live_order_placed(self, pending: PendingLiveOrder, result: OrderResult) -> None:
        self._write({"kind": "live_order_placed", "pending_order": pending, "result_status": result.status, "raw": dict(result.raw or {})})

    def read_all(self) -> list[dict[str, Any]]:
        if not self._path.is_file():
            return []
        return [json.loads(line) for line in self._path.read_text().splitlines() if line.strip()]
