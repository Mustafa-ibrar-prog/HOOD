"""Structured, append-only audit trail of every decision this system makes.

Requirement: "Logging every decision." That means HOLD and NO_TRADE get
logged just as faithfully as EXIT/TARGET_EXIT/STOP_EXIT/BUY — silence is
not an acceptable way to record "nothing happened."

Each entry is one JSON object per line (JSONL) so the log is trivially
appendable, greppable, and diffable, and survives partial writes better
than a single large JSON document would.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from src.logging.app_logger import get_app_logger

if TYPE_CHECKING:
    from src.execution.orders import OrderRequest, OrderResult
    from src.risk.manager import RiskCheckResult
    from src.strategy.decision import Decision


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    """Best-effort conversion of dataclasses/enums/datetimes to something
    json.dumps can serialize, without requiring every caller to pre-flatten
    their evidence dicts."""
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value") and hasattr(value, "name"):  # Enum
        return value.value
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


class DecisionLogger:
    def __init__(self, path: str | Path, also_console: bool = True, app_log_file: str | Path | None = None):
        self._path = Path(path)
        self._also_console = also_console
        self._app_logger = get_app_logger(log_file=app_log_file) if also_console else None

    def _write(self, record: Mapping[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(_jsonable(record), sort_keys=True))
            f.write("\n")
            f.flush()  # audit trail: never buffer this away from disk
        if self._app_logger is not None:
            self._app_logger.info("%s %s: %s", record.get("kind"), record.get("decision", ""), record.get("reason", record.get("message", "")))

    def log_decision(
        self,
        *,
        symbol: str,
        option_id: str | None,
        decision: "Decision",
        reason: str,
        confidence: float,
        evidence: Mapping[str, Any] | None = None,
        pnl_usd: float | None = None,
        risk_checks: tuple["RiskCheckResult", ...] | None = None,
    ) -> None:
        self._write(
            {
                "kind": "decision",
                "timestamp": _utcnow_iso(),
                "symbol": symbol,
                "option_id": option_id,
                "decision": decision,
                "reason": reason,
                "confidence": confidence,
                "evidence": dict(evidence or {}),
                "pnl_usd": pnl_usd,
                "risk_checks": list(risk_checks or ()),
            }
        )

    def log_risk_block(
        self,
        *,
        context: str,
        symbol: str,
        attempted_decision: "Decision",
        blocking_reasons: tuple[str, ...],
    ) -> None:
        self._write(
            {
                "kind": "risk_block",
                "timestamp": _utcnow_iso(),
                "context": context,
                "symbol": symbol,
                "attempted_decision": attempted_decision,
                "blocking_reasons": list(blocking_reasons),
                "reason": f"Blocked by risk controls: {'; '.join(blocking_reasons)}",
            }
        )

    def log_simulated_order(self, order: "OrderRequest", result: "OrderResult") -> None:
        self._write(
            {
                "kind": "simulated_order",
                "timestamp": _utcnow_iso(),
                "order": order,
                "result": result,
                "reason": order.reason,
            }
        )

    def log_simulated_cancel(self, *, account_number: str, order_id: str) -> None:
        self._write(
            {
                "kind": "simulated_cancel",
                "timestamp": _utcnow_iso(),
                "account_number": account_number,
                "order_id": order_id,
                "reason": f"paper-mode cancel of {order_id}",
            }
        )

    def read_all(self) -> list[dict[str, Any]]:
        """Test/debug helper — reads back every record written so far."""
        if not self._path.is_file():
            return []
        with self._path.open() as f:
            return [json.loads(line) for line in f if line.strip()]
