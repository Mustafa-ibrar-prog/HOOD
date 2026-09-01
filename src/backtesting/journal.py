"""The backtest trade journal (Phase 3, section 13).

This mirrors src.logging.trade_journal.TradeJournal's exact philosophy and
append-only-JSONL mechanics deliberately — same "one entry per CLOSED
trade, deterministic, never mutated, never read back to auto-tune
anything" design. It is a SEPARATE class rather than a literal reuse of
TradeJournal because TradeJournalEntry's schema (option_id,
option_description, side in {"long_call","long_put"}, contract_multiplier)
is genuinely options-contract-shaped via OpenPosition's own validation
(side, expiration, contract_multiplier are all required and validated) —
force-fitting an equity backtest trade through OpenPosition would mean
either fabricating fake option fields (violates this codebase's "never
fabricate" convention) or bypassing OpenPosition's validation entirely,
neither of which is honest reuse. TradeJournal itself is completely
untouched by this file — not imported, not modified.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class BacktestTrade:
    trade_id: str
    backtest_id: str
    strategy: str
    symbol: str
    entry_timestamp: datetime
    entry_price: float
    exit_timestamp: datetime
    exit_price: float
    quantity: int
    gross_pnl: float
    fees: float
    slippage: float
    net_pnl: float
    holding_period_minutes: float
    entry_reason: str
    exit_reason: str
    risk_decision: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["entry_timestamp"] = self.entry_timestamp.isoformat()
        d["exit_timestamp"] = self.exit_timestamp.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BacktestTrade":
        return cls(
            trade_id=data["trade_id"],
            backtest_id=data["backtest_id"],
            strategy=data["strategy"],
            symbol=data["symbol"],
            entry_timestamp=datetime.fromisoformat(data["entry_timestamp"]),
            entry_price=float(data["entry_price"]),
            exit_timestamp=datetime.fromisoformat(data["exit_timestamp"]),
            exit_price=float(data["exit_price"]),
            quantity=int(data["quantity"]),
            gross_pnl=float(data["gross_pnl"]),
            fees=float(data["fees"]),
            slippage=float(data["slippage"]),
            net_pnl=float(data["net_pnl"]),
            holding_period_minutes=float(data["holding_period_minutes"]),
            entry_reason=data["entry_reason"],
            exit_reason=data["exit_reason"],
            risk_decision=data["risk_decision"],
        )


class BacktestTradeJournal:
    def __init__(self, path: Path):
        self._path = path

    def record_trade(self, trade: BacktestTrade) -> BacktestTrade:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(trade.to_dict(), sort_keys=True))
            f.write("\n")
            f.flush()
        return trade

    def load_all(self) -> list[BacktestTrade]:
        if not self._path.is_file():
            return []
        raw = self._path.read_text()
        if not raw.strip():
            return []
        return [BacktestTrade.from_dict(json.loads(line)) for line in raw.splitlines() if line.strip()]

    def for_backtest(self, backtest_id: str) -> list[BacktestTrade]:
        """Every trade is traceable back to the experiment that generated
        it, per this phase's requirement — filter by backtest_id."""
        return [t for t in self.load_all() if t.backtest_id == backtest_id]
