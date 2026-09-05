"""Phase 36, Part 8 — strict decision-timestamp semantics.

Three distinct timestamps, never conflated:
  - market_data_timestamp:       when the underlying quote/observation was itself as-of
  - strategy_evaluation_timestamp: when the strategy actually ran `decide()`
  - decision_timestamp:          when the resulting StrategyDecision was recorded

A strategy must never be able to see data timestamped AFTER its own
decision timestamp (no lookahead) -- `assert_no_lookahead` is the
single, reused check for that, mirroring the same "no lookahead"
discipline `src/backtesting/engine.py` already enforces for historical
research, now applied to the live path. Staleness detection reuses the
same numeric comparison `RiskManager.check_data_freshness` already
performs (this module does not duplicate that risk check -- it exists
so staleness can be detected BEFORE a decision is even attempted, not
only as a risk-stage gate after the fact, per Part 8: "a stale quote
must not silently become a valid signal").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class LookaheadViolationError(RuntimeError):
    """Market data timestamped after the decision timestamp was fed to a
    strategy -- the live-path equivalent of `BacktestEngine`'s no-lookahead
    invariant."""


class StaleQuoteError(RuntimeError):
    """A quote is older than the caller-supplied maximum age. Distinct
    from RiskManager.check_data_freshness's RiskCheckResult (which is
    advisory, informational, and can be overridden by a caller reading
    RiskDecision.results) -- this is a hard, upstream fail-closed check
    meant to stop a stale quote from ever reaching a strategy at all."""


@dataclass(frozen=True)
class DecisionTimestamps:
    market_data_timestamp: datetime
    strategy_evaluation_timestamp: datetime
    decision_timestamp: datetime

    def __post_init__(self) -> None:
        assert_no_lookahead(self.market_data_timestamp, self.decision_timestamp)
        if self.strategy_evaluation_timestamp < self.market_data_timestamp:
            raise LookaheadViolationError(
                "strategy_evaluation_timestamp cannot precede the market data it evaluated"
            )
        if self.decision_timestamp < self.strategy_evaluation_timestamp:
            raise LookaheadViolationError(
                "decision_timestamp cannot precede strategy_evaluation_timestamp"
            )

    def market_data_age_seconds(self, now: datetime) -> float:
        return (now - self.market_data_timestamp).total_seconds()

    def is_stale(self, now: datetime, max_age_seconds: float) -> bool:
        return self.market_data_age_seconds(now) > max_age_seconds


def assert_no_lookahead(market_data_timestamp: datetime, decision_timestamp: datetime) -> None:
    if market_data_timestamp > decision_timestamp:
        raise LookaheadViolationError(
            f"market_data_timestamp ({market_data_timestamp.isoformat()}) is after "
            f"decision_timestamp ({decision_timestamp.isoformat()}) -- a decision cannot "
            "be based on data from after it was made."
        )


def assert_quote_not_stale(market_data_timestamp: datetime, *, now: datetime, max_age_seconds: float) -> None:
    age = (now - market_data_timestamp).total_seconds()
    if age > max_age_seconds:
        raise StaleQuoteError(
            f"Quote is stale ({age:.0f}s old, limit {max_age_seconds:.0f}s) -- refusing to "
            "let it silently become a valid signal."
        )
