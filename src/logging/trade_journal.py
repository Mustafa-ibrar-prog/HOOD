"""The cumulative "teaching moment" record: one entry per CLOSED trade
(paper or live), win or loss alike, meant to be read back — by a human, or
by the orchestrating agent as context at the start of a cycle — as the
account's own trading history accumulates.

Deliberately NOT a learning system in the machine-learning sense. Nothing
here mutates RiskManager's limits, the strategy's momentum thresholds, or
position sizing automatically. Two reasons, both hard requirements from
earlier in this project, not just style preferences:

  1. With MAX_TRADES_PER_DAY this low and an account this small, any
     given day produces at most a handful of closed trades — nowhere near
     enough data to "learn" anything statistically real. Auto-tuning a
     threshold off 2-3 trades is overfitting to noise, not learning.
  2. Every risk parameter in this system (MAX_POSITION_SIZE_USD,
     MAX_DAILY_LOSS_USD, MAX_TRADES_PER_DAY, ...) was set by a deliberate
     human decision, not code. A "self-teaching" system that silently
     loosens or tightens those based on its own trade history would be
     exactly the autonomous-risk-control-mutation this project was
     explicitly told never to do.

What this module DOES do: turn every closed trade into a structured,
append-only, human-and-agent-readable record — entry thesis, what actually
happened, why it exited, the realized result, and a short deterministic
takeaway derived strictly from the same evidence the evaluator already
computed (never fabricated commentary). That record is real "teaching" in
the sense that matters here: it makes the account's history visible and
reviewable, cycle over cycle, instead of each trade being forgotten the
moment it closes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from src.position_manager.models import OpenPosition
from src.strategy.decision import Decision, DecisionResult


@dataclass(frozen=True)
class TradeJournalEntry:
    closed_at: datetime
    trade_mode: str  # "paper" | "live"
    symbol: str
    option_id: str
    option_description: str
    side: str  # "long_call" | "long_put"
    setup_name: str
    direction: str  # "bullish" | "bearish"
    catalyst: str
    entry_price: float
    entry_time: datetime
    exit_decision: str  # Decision.value: TARGET_EXIT | STOP_EXIT | EXIT
    exit_reason: str
    realized_pnl_usd: float
    realized_pnl_pct: float
    hold_minutes: float
    momentum_state_at_exit: str
    momentum_signals_at_exit: tuple[str, ...] = field(default_factory=tuple)
    lesson: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "closed_at": self.closed_at.isoformat(),
            "trade_mode": self.trade_mode,
            "symbol": self.symbol,
            "option_id": self.option_id,
            "option_description": self.option_description,
            "side": self.side,
            "setup_name": self.setup_name,
            "direction": self.direction,
            "catalyst": self.catalyst,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time.isoformat(),
            "exit_decision": self.exit_decision,
            "exit_reason": self.exit_reason,
            "realized_pnl_usd": self.realized_pnl_usd,
            "realized_pnl_pct": self.realized_pnl_pct,
            "hold_minutes": self.hold_minutes,
            "momentum_state_at_exit": self.momentum_state_at_exit,
            "momentum_signals_at_exit": list(self.momentum_signals_at_exit),
            "lesson": self.lesson,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TradeJournalEntry":
        return cls(
            closed_at=datetime.fromisoformat(data["closed_at"]),
            trade_mode=data["trade_mode"],
            symbol=data["symbol"],
            option_id=data["option_id"],
            option_description=data["option_description"],
            side=data["side"],
            setup_name=data["setup_name"],
            direction=data["direction"],
            catalyst=data["catalyst"],
            entry_price=float(data["entry_price"]),
            entry_time=datetime.fromisoformat(data["entry_time"]),
            exit_decision=data["exit_decision"],
            exit_reason=data["exit_reason"],
            realized_pnl_usd=float(data["realized_pnl_usd"]),
            realized_pnl_pct=float(data["realized_pnl_pct"]),
            hold_minutes=float(data["hold_minutes"]),
            momentum_state_at_exit=data["momentum_state_at_exit"],
            momentum_signals_at_exit=tuple(data.get("momentum_signals_at_exit", ())),
            lesson=data.get("lesson", ""),
        )


def _derive_lesson(exit_decision: Decision, exit_reason: str, pnl_usd: float) -> str:
    """Deterministic, template-based takeaway — derived strictly from the
    decision category and reason string the evaluator already produced.
    Never invents an insight the evidence doesn't support."""
    if "Trailing exit" in exit_reason:
        return (
            "Trailing stop did its job: locked in a real gain once price gave back "
            "a defined fraction of the peak, rather than riding it back down."
            if pnl_usd > 0
            else "Trailing stop fired on a position that had gone profitable then reversed."
        )
    if exit_decision is Decision.STOP_EXIT:
        return "Hard stop — thesis invalidated or the loss limit was hit. The stop capped the downside as designed; review whether the entry signal itself was the weak point."
    if exit_decision is Decision.TARGET_EXIT:
        return "Profit target reached with momentum no longer confirming further continuation — took the planned win rather than risking a giveback."
    if exit_decision is Decision.EXIT and pnl_usd > 0:
        return "Exited early on weakening/reversing momentum evidence, before the target — the evidence-based exit path working as intended."
    if exit_decision is Decision.EXIT:
        return "Early exit on weakening evidence while still at a loss — cut before it could develop into a stop-out."
    return f"Closed via {exit_decision.value}: {exit_reason}"


class TradeJournal:
    def __init__(self, path: Path):
        self._path = path

    def load(self) -> list[TradeJournalEntry]:
        if not self._path.is_file():
            return []
        raw = self._path.read_text()
        if not raw.strip():
            return []
        return [TradeJournalEntry.from_dict(json.loads(line)) for line in raw.splitlines() if line.strip()]

    def record_close(
        self,
        *,
        position: OpenPosition,
        result: DecisionResult,
        exit_price: float,
        realized_pnl_usd: float,
        trade_mode: str,
        now: datetime,
    ) -> TradeJournalEntry:
        """Called at the moment a position actually closes (paper fill or
        confirmed live fill) — never for a HOLD, and never for a live order
        that only reached pending_approval (nothing closed yet)."""
        hold_minutes = (now - position.entry_time).total_seconds() / 60
        pnl_pct = (
            (exit_price - position.entry_price) / position.entry_price if position.entry_price else 0.0
        )
        momentum_state = str(result.evidence.get("momentum_state", "unknown"))
        momentum_signals = tuple(result.evidence.get("momentum_signals", ()))

        entry = TradeJournalEntry(
            closed_at=now,
            trade_mode=trade_mode,
            symbol=position.symbol,
            option_id=position.option_id,
            option_description=position.option_description,
            side=position.side,
            setup_name=position.thesis.setup_name,
            direction=position.thesis.direction,
            catalyst=position.thesis.catalyst,
            entry_price=position.entry_price,
            entry_time=position.entry_time,
            exit_decision=result.decision.value,
            exit_reason=result.reason,
            realized_pnl_usd=realized_pnl_usd,
            realized_pnl_pct=pnl_pct,
            hold_minutes=hold_minutes,
            momentum_state_at_exit=momentum_state,
            momentum_signals_at_exit=momentum_signals,
            lesson=_derive_lesson(result.decision, result.reason, realized_pnl_usd),
        )

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(entry.to_dict(), sort_keys=True))
            f.write("\n")
            f.flush()
        return entry

    def summary(self) -> dict[str, Any]:
        """Cheap aggregate stats over everything recorded so far — what a
        human (or the agent, at the start of a cycle) would actually want
        to see at a glance: win rate, total realized P&L, and how often
        each exit path fired. Read-only; never used to mutate config."""
        entries = self.load()
        if not entries:
            return {"trade_count": 0}
        wins = [e for e in entries if e.realized_pnl_usd > 0]
        losses = [e for e in entries if e.realized_pnl_usd <= 0]
        by_exit_type: dict[str, int] = {}
        for e in entries:
            by_exit_type[e.exit_decision] = by_exit_type.get(e.exit_decision, 0) + 1
        return {
            "trade_count": len(entries),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate": len(wins) / len(entries),
            "total_realized_pnl_usd": round(sum(e.realized_pnl_usd for e in entries), 2),
            "exit_type_counts": by_exit_type,
        }
