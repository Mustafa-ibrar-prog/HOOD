"""The backtest strategy interface (Phase 3, section 22).

Phase 2's src.strategy.base.Strategy (options-chain scanning:
scan(market, universe) -> list[SetupCandidate]) doesn't fit an event-driven,
per-bar equity replay loop — it's shaped around scanning an entire universe
once per cycle and proposing option contracts, not "given the history up to
this bar, what do you want to do now." Rather than force-fit that interface
or rebuild it, this is a narrower, purpose-built interface for backtesting,
spiritually identical in the one respect that matters most: a strategy only
ever PROPOSES. It cannot access anything else.

A BacktestStrategy:
  - receives only `history` (every Bar up to and including the current one
    for one symbol — never a future bar) and `features` (this bar's
    already-computed, causal feature values from src.features).
  - returns None or a Signal — a direction and a confidence, nothing more.
  - has no reference to a database, Robinhood, the event queue, the
    portfolio, or any order-placement method. It cannot submit an order,
    modify a position, or bypass risk review — only BacktestEngine turns a
    Signal into an order, and only after PositionSizer and
    BacktestRiskAdapter both look at it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping, Sequence

from src.data.bar import Bar


@dataclass(frozen=True)
class Signal:
    direction: str  # "LONG" | "FLAT" — SHORT is reserved, not implemented (see portfolio.py's Position docstring)
    strength: float = 1.0  # 0.0-1.0, strategy-defined confidence/sizing hint
    reason: str = ""

    def __post_init__(self) -> None:
        if self.direction not in ("LONG", "FLAT"):
            raise ValueError("direction must be 'LONG' or 'FLAT' — SHORT is not implemented")
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError("strength must be within [0.0, 1.0]")


class BacktestStrategy(ABC):
    name: str = "unnamed-backtest-strategy"
    version: str = "1.0"

    @abstractmethod
    def on_bar(self, history: Sequence[Bar], features: Mapping[str, float | None]) -> Signal | None:
        """Called once per bar, per symbol, in chronological order.
        `history[-1]` is the current bar; `history[:-1]` is everything
        before it — there is never a bar beyond `history[-1]` in this
        list. Returning None means "no opinion this bar" (equivalent to
        holding whatever position already exists)."""
        raise NotImplementedError
