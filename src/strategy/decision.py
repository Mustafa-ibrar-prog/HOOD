"""The decision model shared by the scanner (new trades) and the position
manager (open trades).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class Decision(str, Enum):
    """Every action this system can ever recommend or take.

    BUY          - open a new position (scanner only).
    HOLD         - keep an open position exactly as-is.
    EXIT         - close an open position early because evidence shows the
                   move has weakened or peaked, independent of whether a
                   profit target has been reached.
    TARGET_EXIT  - close an open position because its profit target has
                   been reached and there is no strong evidence to keep
                   riding it further.
    STOP_EXIT    - close an open position because a hard risk control was
                   breached (max loss, thesis invalidated, expiration risk).
    NO_TRADE     - scanner found nothing that clears the bar, or risk
                   controls blocked every candidate. Explicitly loggable so
                   "did nothing" is always visible in the audit trail.
    """

    BUY = "BUY"
    HOLD = "HOLD"
    EXIT = "EXIT"
    TARGET_EXIT = "TARGET_EXIT"
    STOP_EXIT = "STOP_EXIT"
    NO_TRADE = "NO_TRADE"


# Any decision that means "close the position."
EXIT_DECISIONS = frozenset({Decision.EXIT, Decision.TARGET_EXIT, Decision.STOP_EXIT})

# Decisions the position manager (monitoring an already-open position) is
# allowed to produce. BUY/NO_TRADE belong to the scanner, not the monitor.
POSITION_MONITOR_DECISIONS = frozenset(
    {Decision.HOLD, Decision.EXIT, Decision.TARGET_EXIT, Decision.STOP_EXIT}
)


@dataclass(frozen=True)
class TradeThesis:
    """The reasoning captured at entry time, so later evaluations can check
    whether the original reason for the trade still holds."""

    setup_name: str
    direction: str  # "bullish" or "bearish"
    catalyst: str
    invalidation: str
    profit_target_usd: float | None = None
    stop_loss_usd: float | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if self.direction.lower() not in {"bullish", "bearish"}:
            raise ValueError("direction must be 'bullish' or 'bearish'")


@dataclass(frozen=True)
class DecisionResult:
    """The output of any evaluation: what to do, why, how confident, and
    the raw evidence that led there — this is what gets logged, every time.
    """

    decision: Decision
    reason: str
    confidence: float  # 0.0 - 1.0
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if not self.reason:
            raise ValueError("reason must not be empty — every decision must be explainable")
