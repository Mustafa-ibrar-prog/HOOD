"""Phase 36, Part 2 — the structured decision object every production
strategy must return.

`StrategyDecision` is pure data. It has no `submit()`, no reference to a
broker, an execution gateway, or any authorization/emergency-stop store
-- a strategy cannot possibly place an order through this object, only
describe what it would like to happen (Part 3: 'Do not allow a strategy
to directly submit an order'). Everything downstream (risk, sizing,
authorization, execution) re-derives its own numbers from real state; a
strategy's own `quantity_recommendation`/`signal_score`/`confidence` are
never trusted as the final word (see risk_handoff.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Mapping


class DecisionType(str, Enum):
    NO_TRADE = "NO_TRADE"
    ENTER = "ENTER"
    EXIT = "EXIT"
    HOLD = "HOLD"


class MalformedDecisionError(ValueError):
    """Raised by StrategyDecision.__post_init__ when the fields present
    are inconsistent with the declared `decision` type -- e.g. an ENTER
    with no option_id, or a NO_TRADE that somehow carries a quantity
    recommendation. Part 20: a malformed decision must fail closed here,
    before it ever reaches risk/ranking."""


@dataclass(frozen=True)
class StrategyDecision:
    strategy_id: str
    timestamp: datetime
    decision: DecisionType

    # Contract identification -- required for ENTER/EXIT, optional (None)
    # for NO_TRADE/HOLD, which may not reference any specific contract.
    underlying: str | None = None
    option_id: str | None = None
    option_type: str | None = None  # "call" | "put"
    strike: float | None = None
    expiration: date | None = None
    side: str | None = None  # "long_call" | "long_put" -- the POSITION side, never an order side

    quantity_recommendation: int | None = None  # a hint only -- see risk_handoff.py
    signal_score: float | None = None
    expected_holding_period_minutes: float | None = None
    reason: str = ""
    features: Mapping[str, Any] = field(default_factory=dict)
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.option_type is not None and self.option_type not in {"call", "put"}:
            raise MalformedDecisionError(f"option_type must be 'call' or 'put', got {self.option_type!r}")
        if self.side is not None and self.side not in {"long_call", "long_put"}:
            raise MalformedDecisionError(f"side must be 'long_call' or 'long_put', got {self.side!r}")
        if self.quantity_recommendation is not None and self.quantity_recommendation <= 0:
            raise MalformedDecisionError("quantity_recommendation must be > 0 when provided")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise MalformedDecisionError(f"confidence must be in [0, 1], got {self.confidence}")

        if self.decision == DecisionType.ENTER:
            missing = [
                name for name, val in (
                    ("underlying", self.underlying), ("option_id", self.option_id),
                    ("side", self.side), ("quantity_recommendation", self.quantity_recommendation),
                ) if val is None
            ]
            if missing:
                raise MalformedDecisionError(f"ENTER decision is missing required field(s): {missing}")
        elif self.decision == DecisionType.EXIT:
            missing = [name for name, val in (("underlying", self.underlying), ("option_id", self.option_id)) if val is None]
            if missing:
                raise MalformedDecisionError(f"EXIT decision is missing required field(s): {missing}")
        elif self.decision in (DecisionType.NO_TRADE, DecisionType.HOLD):
            if self.quantity_recommendation is not None:
                raise MalformedDecisionError(f"{self.decision.value} must not carry a quantity_recommendation")

    # Deliberately NO submit()/place_order()/to_order_request() method on
    # this class -- constructing an OrderRequest from a StrategyDecision
    # is risk_handoff.py's job, downstream of a real RiskDecision, never
    # this object's own responsibility.
