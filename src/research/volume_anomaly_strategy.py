"""Phase 8: the tradeable, long-only translation of P7-VOLANOM-A's
discovery-stage finding.

IMPORTANT — a translation choice, not a redefinition: P7-VOLANOM-A's
FROZEN discovery hypothesis (src.research.hypothesis_generator, family
VOLUME_ANOMALY) tests whether RelativeVolume predicts the MAGNITUDE of
the subsequent move (|future_return|) — it is explicitly NOT directional
("not directional — informational only at the discovery stage"). Phase 8
requires a tradeable, long-only mechanism (Part 2/3 of the Phase 8
prompt), which the discovery hypothesis alone does not specify. The
LEAST-BIASED way to convert a magnitude-only finding into a directional
test — without smuggling in a new filter chosen after seeing results, and
without silently retesting the ALREADY-TESTED P7-VPC-A (volume-confirmed
momentum) hypothesis under a new name — is to go LONG UNCONDITIONALLY on
every anomaly signal, regardless of the bar's own return sign. See
scripts/phase8_step1_development_preregistration.py for the full,
pre-registered reasoning; this is recorded there BEFORE any backtest runs.

If this comes back near-zero net expectancy, that is an EXPECTED,
non-failure outcome — it would mean the magnitude relationship is
genuinely symmetric (predicts bigger moves in either direction) rather
than a directional edge, exactly what the original discovery hypothesis
always said it was testing.

The underlying feature (RelativeVolume, src.features.volume) is used
completely unmodified — only the entry/exit/holding-period MECHANISM
around it is new, exactly as Part 2 directs.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from src.data.bar import Bar
from src.features.engine import FeatureEngine
from src.features.volume import RelativeVolume
from src.research.strategy import ResearchSignal, ResearchStrategy, ResearchStrategySpec


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


class VolumeAnomalyLongStrategy(ResearchStrategy):
    """LONG, unconditionally, when RelativeVolume(baseline_lookback) at
    bar t exceeds anomaly_threshold; held for EXACTLY holding_period_bars
    bars, then FLAT — no early exit, no stop-loss/take-profit (Part 2's
    explicit instruction). No new position is opened while one is already
    held for this symbol. `feature_engine()` uses RelativeVolume with
    NOTHING else — the exact P7-VOLANOM-A feature, unmodified."""

    def __init__(self, *, strategy_id: str, baseline_lookback: int, anomaly_threshold: float, holding_period_bars: int, universe: Sequence[str], prediction_horizon_bars: int = 5):
        if baseline_lookback < 1:
            raise ValueError("baseline_lookback must be >= 1")
        if holding_period_bars < 1:
            raise ValueError("holding_period_bars must be >= 1")
        self.baseline_lookback = baseline_lookback
        self.anomaly_threshold = anomaly_threshold
        self.holding_period_bars = holding_period_bars
        self._feature_name = f"relative_volume_{baseline_lookback}"
        self._entry_bar_index: dict[str, int] = {}  # per-symbol mutable state — a FRESH instance is required per backtest run (see factory pattern in scripts/phase8_*)
        self.spec = ResearchStrategySpec(
            strategy_id=strategy_id, name=f"Volume Anomaly Long (lookback={baseline_lookback}, threshold={anomaly_threshold}, hold={holding_period_bars})", version="1.0",
            hypothesis_id="P7-VOLANOM-A-DEV1", universe=tuple(universe), timeframe="day",
            parameters={"baseline_lookback": baseline_lookback, "anomaly_threshold": anomaly_threshold, "holding_period_bars": holding_period_bars},
            holding_period_bars=holding_period_bars, prediction_horizon_bars=prediction_horizon_bars, expected_regime="any",
        )

    def feature_engine(self) -> FeatureEngine:
        return FeatureEngine([RelativeVolume(self.baseline_lookback)])

    def generate_signal(self, history: Sequence[Bar], features: Mapping[str, float | None]) -> ResearchSignal | None:
        bar = history[-1]
        symbol = bar.symbol
        current_index = len(history) - 1

        if symbol in self._entry_bar_index:
            bars_held = current_index - self._entry_bar_index[symbol]
            if bars_held >= self.holding_period_bars:
                del self._entry_bar_index[symbol]
                return ResearchSignal(
                    timestamp=bar.timestamp, symbol=symbol, strategy_id=self.spec.strategy_id, strategy_version=self.spec.version,
                    direction="FLAT", signal_strength=None, target_position=None, feature_values=dict(features),
                )
            return None  # still within the fixed holding period — no new opinion, no early exit

        rv = features.get(self._feature_name)
        if rv is None or rv <= self.anomaly_threshold:
            return None

        self._entry_bar_index[symbol] = current_index
        strength = _clip01((rv - self.anomaly_threshold) / max(self.anomaly_threshold, 0.5))
        return ResearchSignal(
            timestamp=bar.timestamp, symbol=symbol, strategy_id=self.spec.strategy_id, strategy_version=self.spec.version,
            direction="LONG", signal_strength=strength, target_position=None, feature_values=dict(features),
        )
