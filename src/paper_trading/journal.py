"""Phase 40, Part 19 — the complete PAPER_EXPERIMENT trade record.

ADDITIVE to (never a replacement of) the existing, general-purpose
`src.logging.trade_journal.TradeJournal` — `run_trading_cycle` already
writes a `TradeJournalEntry` for every closed trade regardless of Phase
40; this module records the RICHER, experiment-specific superset Part 19
lists (experiment ID, strategy hash, observation cycle, strike/DTE/
moneyness, entry/exit bid AND ask separately, gross vs net P&L, spread
cost, slippage, fees, MFE/MAE) alongside it, in its own append-only
store, always labeled `PAPER_EXPERIMENT` — never `LIVE_TRADE`
(`PaperExperimentTradeRecord.label` is hard-coded and cannot be
constructed as anything else; see `test_phase40_safety.py`).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

PAPER_EXPERIMENT_LABEL = "PAPER_EXPERIMENT"


@dataclass(frozen=True)
class PaperExperimentTradeRecord:
    label: str  # always PAPER_EXPERIMENT_LABEL -- enforced in __post_init__
    experiment_id: str
    trade_id: str  # deterministic: sha256(experiment_id + option_id + entry_observation_cycle_id)[:24]
    strategy_id: str
    strategy_content_hash: str
    entry_observation_cycle_id: str
    exit_observation_cycle_id: str | None
    entry_timestamp: datetime
    exit_timestamp: datetime | None
    symbol: str
    option_id: str
    strike: float | None
    expiration: date | None
    option_type: str | None  # "call" | "put"
    dte_at_entry: int | None
    moneyness_at_entry: float | None
    entry_bid: float | None
    entry_ask: float | None
    entry_fill: float | None  # the REAL simulated fill price (ask), from PaperExecutionGateway
    exit_bid: float | None
    exit_ask: float | None
    exit_fill: float | None  # the REAL simulated fill price (bid)
    quantity: int
    gross_pnl_usd: float | None
    spread_cost_usd: float | None
    slippage_usd: float | None
    fees_usd: float | None
    net_pnl_usd: float | None
    return_pct: float | None  # net_pnl_usd / (entry_fill * quantity * 100)
    mfe_pct: float | None  # best unrealized mid-based excursion vs entry_fill, over the observed holding path
    mae_pct: float | None  # worst unrealized mid-based excursion vs entry_fill
    exit_reason: str | None
    slippage_tier: str  # SlippageAssumptionTier.value used for the cost breakdown

    def __post_init__(self) -> None:
        if self.label != PAPER_EXPERIMENT_LABEL:
            raise ValueError(f"label must be {PAPER_EXPERIMENT_LABEL!r}, got {self.label!r} — never LIVE_TRADE")

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label, "experiment_id": self.experiment_id, "trade_id": self.trade_id,
            "strategy_id": self.strategy_id, "strategy_content_hash": self.strategy_content_hash,
            "entry_observation_cycle_id": self.entry_observation_cycle_id,
            "exit_observation_cycle_id": self.exit_observation_cycle_id,
            "entry_timestamp": self.entry_timestamp.isoformat(),
            "exit_timestamp": self.exit_timestamp.isoformat() if self.exit_timestamp else None,
            "symbol": self.symbol, "option_id": self.option_id, "strike": self.strike,
            "expiration": self.expiration.isoformat() if self.expiration else None, "option_type": self.option_type,
            "dte_at_entry": self.dte_at_entry, "moneyness_at_entry": self.moneyness_at_entry,
            "entry_bid": self.entry_bid, "entry_ask": self.entry_ask, "entry_fill": self.entry_fill,
            "exit_bid": self.exit_bid, "exit_ask": self.exit_ask, "exit_fill": self.exit_fill,
            "quantity": self.quantity, "gross_pnl_usd": self.gross_pnl_usd, "spread_cost_usd": self.spread_cost_usd,
            "slippage_usd": self.slippage_usd, "fees_usd": self.fees_usd, "net_pnl_usd": self.net_pnl_usd,
            "return_pct": self.return_pct, "mfe_pct": self.mfe_pct, "mae_pct": self.mae_pct,
            "exit_reason": self.exit_reason, "slippage_tier": self.slippage_tier,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PaperExperimentTradeRecord":
        return cls(
            label=data["label"], experiment_id=data["experiment_id"], trade_id=data["trade_id"],
            strategy_id=data["strategy_id"], strategy_content_hash=data["strategy_content_hash"],
            entry_observation_cycle_id=data["entry_observation_cycle_id"],
            exit_observation_cycle_id=data.get("exit_observation_cycle_id"),
            entry_timestamp=datetime.fromisoformat(data["entry_timestamp"]),
            exit_timestamp=datetime.fromisoformat(data["exit_timestamp"]) if data.get("exit_timestamp") else None,
            symbol=data["symbol"], option_id=data["option_id"], strike=data.get("strike"),
            expiration=date.fromisoformat(data["expiration"]) if data.get("expiration") else None,
            option_type=data.get("option_type"), dte_at_entry=data.get("dte_at_entry"),
            moneyness_at_entry=data.get("moneyness_at_entry"), entry_bid=data.get("entry_bid"),
            entry_ask=data.get("entry_ask"), entry_fill=data.get("entry_fill"), exit_bid=data.get("exit_bid"),
            exit_ask=data.get("exit_ask"), exit_fill=data.get("exit_fill"), quantity=int(data["quantity"]),
            gross_pnl_usd=data.get("gross_pnl_usd"), spread_cost_usd=data.get("spread_cost_usd"),
            slippage_usd=data.get("slippage_usd"), fees_usd=data.get("fees_usd"), net_pnl_usd=data.get("net_pnl_usd"),
            return_pct=data.get("return_pct"), mfe_pct=data.get("mfe_pct"), mae_pct=data.get("mae_pct"),
            exit_reason=data.get("exit_reason"), slippage_tier=data.get("slippage_tier", ""),
        )


def deterministic_trade_id(*, experiment_id: str, option_id: str, entry_observation_cycle_id: str) -> str:
    blob = f"{experiment_id}|{option_id}|{entry_observation_cycle_id}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


class PaperExperimentTradeStore:
    """Append-only JSONL, keyed by `trade_id` for dedup (Part 23: 'Never
    duplicate a trade because the process restarted'). An OPEN trade is
    appended once at entry (exit fields None); on close, a NEW row with
    the SAME trade_id plus exit fields is appended and `load_all()`
    returns only the LATEST row per trade_id — an update, not a second
    trade, exactly like Phase 37's NormalizedOptionStore per-cycle rows
    but collapsed to "latest wins" per trade_id rather than kept as
    separate per-cycle observations (a trade has exactly one current
    state, unlike a repeated market observation)."""

    def __init__(self, path: Path):
        self._path = Path(path)

    def load_all(self) -> list[PaperExperimentTradeRecord]:
        if not self._path.is_file():
            return []
        latest: dict[str, PaperExperimentTradeRecord] = {}
        for line in self._path.read_text().splitlines():
            if line.strip():
                record = PaperExperimentTradeRecord.from_dict(json.loads(line))
                latest[record.trade_id] = record  # later lines (later appends) win
        return list(latest.values())

    def get(self, trade_id: str) -> PaperExperimentTradeRecord | None:
        for r in self.load_all():
            if r.trade_id == trade_id:
                return r
        return None

    def append(self, record: PaperExperimentTradeRecord) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as fh:
            fh.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
