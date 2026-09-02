"""Phase 11, Part 9: bridges a precomputed exposure series
(src.research.exposure_mechanisms.compute_exposure_series — or a shuffled/
randomized variant of one) into Phase 3's real, unmodified BacktestEngine
via the standard ResearchStrategy interface (src.research.strategy,
Phase 4, unmodified).

Deliberately does NOT compute exposure live inside generate_signal(): the
exposure decision is fully determined by causal, already-computed feature
history (proven no-lookahead by
tests/test_exposure_mechanisms.py::test_compute_exposure_series_does_not_leak_future_data),
so precomputing it once, outside the backtest loop, is both a
performance win AND what makes the placebo controls (Parts 25-26) exactly
comparable to the real mechanism they're testing against — same
rebalance timestamps, same clamped exposure bounds, only the VALUES (or
their temporal assignment) differ.

Execution timing discipline (Part 9's "no same-bar execution") is
enforced entirely by BacktestEngine's own ExecutionModel.delay_bars()
mechanism — this strategy only ever proposes; scheduling the fill for a
future bar is the engine's job, exactly as for every other strategy in
this codebase.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from src.data.bar import Bar
from src.features.engine import FeatureEngine
from src.research.strategy import ResearchSignal, ResearchStrategy, ResearchStrategySpec


class PrecomputedExposureStrategy(ResearchStrategy):
    """Plays back a precomputed, per-symbol exposure series. Emits a LONG
    signal with `signal_strength = exposure` ONLY at the timestamps the
    series actually has a value for (the rebalance schedule baked into
    how the series was built) — every other bar returns None, meaning
    "hold whatever is already held," exactly matching Part 7's
    "rebalance frequency" semantics."""

    def __init__(self, *, strategy_id: str, exposure_by_symbol: Mapping[str, Mapping[object, float]], universe: Sequence[str], hypothesis_id: str, version: str = "1.0"):
        self._exposure_by_symbol = exposure_by_symbol
        self.spec = ResearchStrategySpec(
            strategy_id=strategy_id, name=strategy_id, version=version, hypothesis_id=hypothesis_id, universe=tuple(universe),
            timeframe="day", parameters={}, holding_period_bars=1, prediction_horizon_bars=1, expected_regime="any",
        )

    def feature_engine(self) -> FeatureEngine:
        # Exposure is already fully precomputed — no LIVE feature
        # computation is needed inside the backtest loop itself.
        return FeatureEngine([])

    def generate_signal(self, history: Sequence[Bar], features: Mapping[str, float | None]) -> ResearchSignal | None:
        bar = history[-1]
        symbol = bar.symbol
        exposure = self._exposure_by_symbol.get(symbol, {}).get(bar.timestamp)
        if exposure is None:
            return None
        if not 0.0 <= exposure <= 1.0:
            raise ValueError(f"precomputed exposure {exposure} for {symbol}@{bar.timestamp} is outside [0, 1] — a bug in the mechanism that produced it, not clamped here defensively on purpose (silently clamping would hide that bug)")
        return ResearchSignal(
            timestamp=bar.timestamp, symbol=symbol, strategy_id=self.spec.strategy_id, strategy_version=self.spec.version,
            direction="LONG", signal_strength=exposure, target_position=exposure, feature_values=dict(features),
        )
