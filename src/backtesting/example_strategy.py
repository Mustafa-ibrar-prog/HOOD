"""ONE simple example strategy, built solely to exercise the backtesting
engine end-to-end (Phase 3, section 23).

NO EDGE CLAIMED. This is a plain fast/slow moving-average crossover — a
textbook-simple, fully deterministic rule chosen specifically because its
correct output is easy to verify by hand. Its only job is to prove that
data -> features -> signal -> order -> fill -> position -> P&L works
correctly through the real engine. Do not read anything about "this
strategy makes money" into its presence here — strategy research and
validation is explicitly next phase's job, not this one's.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from src.data.bar import Bar
from src.backtesting.strategy import BacktestStrategy, Signal
from src.features.engine import FeatureEngine
from src.features.momentum import MovingAverage


class MovingAverageCrossoverStrategy(BacktestStrategy):
    """LONG when the fast SMA is above the slow SMA, FLAT otherwise. Uses
    the exact same src.features.momentum.MovingAverage feature computed by
    the engine's FeatureEngine — this strategy trusts the engine's already
    -causal feature values rather than computing anything itself from
    `history` directly, which is the intended integration pattern."""

    name = "ma-crossover-example"
    version = "1.0"

    def __init__(self, fast_window: int = 5, slow_window: int = 20):
        if fast_window >= slow_window:
            raise ValueError("fast_window must be < slow_window")
        self.fast_window = fast_window
        self.slow_window = slow_window
        self._fast_name = f"sma_{fast_window}"
        self._slow_name = f"sma_{slow_window}"

    def feature_engine(self) -> FeatureEngine:
        """Convenience factory for the exact FeatureEngine this strategy
        needs — callers wire this into BacktestEngine(feature_engine=...)."""
        return FeatureEngine([MovingAverage(self.fast_window), MovingAverage(self.slow_window)])

    def on_bar(self, history: Sequence[Bar], features: Mapping[str, float | None]) -> Signal | None:
        fast = features.get(self._fast_name)
        slow = features.get(self._slow_name)
        if fast is None or slow is None:
            return None  # not enough history yet — no opinion, not a guess
        if fast > slow:
            return Signal(direction="LONG", strength=1.0, reason=f"{self._fast_name}={fast:.4f} > {self._slow_name}={slow:.4f}")
        return Signal(direction="FLAT", strength=1.0, reason=f"{self._fast_name}={fast:.4f} <= {self._slow_name}={slow:.4f}")
