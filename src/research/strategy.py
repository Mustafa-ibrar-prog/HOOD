"""The standardized research-strategy interface (Phase 4, section 2).

A ResearchStrategy is a fully-specified, reproducible research object: it
carries its own hypothesis linkage, universe, timeframe, parameters,
holding period, expected regime, and prediction horizon — everything
needed to reconstruct exactly what was tested, not just a signal function.

Like src.backtesting.strategy.BacktestStrategy, it has NO reference to
Robinhood, live orders, live account state, the database, or the event
queue — it only ever receives causal history + this bar's already-
computed features and returns a signal proposal. ResearchStrategyAdapter
below is the (thin, zero-duplication) bridge that lets any ResearchStrategy
run through Phase 3's real BacktestEngine unchanged.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from src.backtesting.strategy import BacktestStrategy, Signal
from src.data.bar import Bar
from src.features.engine import FeatureEngine


@dataclass(frozen=True)
class ResearchStrategySpec:
    """Static, reproducible metadata — everything section 2 asks a
    research strategy to define, in one place."""

    strategy_id: str  # e.g. "MOM-001"
    name: str
    version: str
    hypothesis_id: str  # FK into HypothesisRegistry
    universe: tuple[str, ...]
    timeframe: str
    parameters: Mapping[str, Any]
    holding_period_bars: int
    prediction_horizon_bars: int
    expected_regime: str  # e.g. "trending", "any", "low_volatility"


@dataclass(frozen=True)
class ResearchSignal:
    """The standardized signal every research strategy must produce
    (Phase 4, section 5)."""

    timestamp: datetime
    symbol: str
    strategy_id: str
    strategy_version: str
    direction: str  # "LONG" | "FLAT"
    # NEVER a fabricated confidence score — None unless the strategy
    # derives this mathematically from its own feature values (documented
    # per-strategy exactly how). Contrast with a made-up "0.72 confidence".
    signal_strength: float | None
    target_position: float | None  # a sizing hint (e.g. desired weight), optional
    feature_values: Mapping[str, float | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.direction not in ("LONG", "FLAT"):
            raise ValueError("direction must be 'LONG' or 'FLAT'")
        if self.signal_strength is not None and not 0.0 <= self.signal_strength <= 1.0:
            raise ValueError("signal_strength must be within [0.0, 1.0] when provided")


class ResearchStrategy(ABC):
    spec: ResearchStrategySpec

    @abstractmethod
    def feature_engine(self) -> FeatureEngine:
        raise NotImplementedError

    @abstractmethod
    def generate_signal(self, history: Sequence[Bar], features: Mapping[str, float | None]) -> ResearchSignal | None:
        """`history[-1]` is the current bar; nothing beyond it is ever
        visible. Returns None for "no opinion this bar"."""
        raise NotImplementedError


class ResearchStrategyBacktestAdapter(BacktestStrategy):
    """Bridges a ResearchStrategy into Phase 3's BacktestEngine, unchanged
    — zero duplication of the event loop, fill simulation, portfolio
    accounting, or risk integration. This is the "integrate with the
    existing architecture" move: every backtest this phase runs goes
    through the exact same engine.py as Phase 3's example strategy did."""

    def __init__(self, research_strategy: ResearchStrategy):
        self._research_strategy = research_strategy
        self.name = research_strategy.spec.strategy_id
        self.version = research_strategy.spec.version
        self.last_signal: ResearchSignal | None = None

    def on_bar(self, history: Sequence[Bar], features: Mapping[str, float | None]) -> Signal | None:
        research_signal = self._research_strategy.generate_signal(history, features)
        if research_signal is None:
            return None
        self.last_signal = research_signal
        strength = research_signal.signal_strength if research_signal.signal_strength is not None else 1.0
        return Signal(direction=research_signal.direction, strength=strength, reason=f"{research_signal.strategy_id}")
