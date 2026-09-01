"""A small, clean set of independently-testable research strategy
families (Phase 4, sections 4 and 24). Exactly the six used in this
phase's first research campaign — momentum, mean reversion, a volatility-
regime strategy, and a volume-confirmed momentum strategy. None of these
are assumed to work; that's what the campaign evaluates.

`signal_strength` on every ResearchSignal below is a documented, honest
linear transform of the strategy's OWN feature magnitude, clipped to
[0, 1] — never a fabricated probability/confidence number (Phase 4,
section 5's explicit requirement).
"""

from __future__ import annotations

from typing import Mapping, Sequence

from src.data.bar import Bar
from src.features.engine import FeatureEngine
from src.features.mean_reversion import RollingZScore
from src.features.momentum import RateOfChange
from src.features.regime import TrendRegime, VolatilityRegime
from src.features.volume import RelativeVolume
from src.research.hypothesis import Hypothesis
from src.research.strategy import ResearchSignal, ResearchStrategy, ResearchStrategySpec


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


class MomentumStrategy(ResearchStrategy):
    """LONG when trailing `lookback`-bar return exceeds `entry_threshold`;
    FLAT when it falls to/below `exit_threshold`."""

    def __init__(self, *, strategy_id: str, lookback: int, universe: Sequence[str], entry_threshold: float = 0.02, exit_threshold: float = 0.0, prediction_horizon_bars: int = 5, holding_period_bars: int = 5):
        self.lookback = lookback
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self._feature_name = f"roc_{lookback}"
        self.spec = ResearchStrategySpec(
            strategy_id=strategy_id, name=f"{lookback}-Day Momentum", version="1.0",
            hypothesis_id=strategy_id, universe=tuple(universe), timeframe="day",
            parameters={"lookback": lookback, "entry_threshold": entry_threshold, "exit_threshold": exit_threshold},
            holding_period_bars=holding_period_bars, prediction_horizon_bars=prediction_horizon_bars, expected_regime="trending",
        )

    def feature_engine(self) -> FeatureEngine:
        return FeatureEngine([RateOfChange(self.lookback)])

    def generate_signal(self, history: Sequence[Bar], features: Mapping[str, float | None]) -> ResearchSignal | None:
        roc = features.get(self._feature_name)
        if roc is None:
            return None
        roc_frac = roc / 100.0  # RateOfChange returns percent units
        direction = "LONG" if roc_frac > self.entry_threshold else "FLAT" if roc_frac <= self.exit_threshold else None
        if direction is None:
            return None
        bar = history[-1]
        strength = _clip01(abs(roc_frac) / max(self.entry_threshold * 3, 0.01))
        return ResearchSignal(
            timestamp=bar.timestamp, symbol=bar.symbol, strategy_id=self.spec.strategy_id, strategy_version=self.spec.version,
            direction=direction, signal_strength=strength, target_position=None, feature_values=dict(features),
        )


class MeanReversionStrategy(ResearchStrategy):
    """LONG when the rolling z-score of price is very NEGATIVE (an
    oversold extreme), betting on reversion toward the mean; FLAT once
    the z-score recovers to/above `exit_z`."""

    def __init__(self, *, strategy_id: str, lookback: int, universe: Sequence[str], entry_z: float = -1.5, exit_z: float = 0.0, prediction_horizon_bars: int = 5, holding_period_bars: int = 5):
        self.lookback = lookback
        self.entry_z = entry_z
        self.exit_z = exit_z
        self._feature_name = f"zscore_{lookback}"
        self.spec = ResearchStrategySpec(
            strategy_id=strategy_id, name=f"{lookback}-Day Mean Reversion", version="1.0",
            hypothesis_id=strategy_id, universe=tuple(universe), timeframe="day",
            parameters={"lookback": lookback, "entry_z": entry_z, "exit_z": exit_z},
            holding_period_bars=holding_period_bars, prediction_horizon_bars=prediction_horizon_bars, expected_regime="any",
        )

    def feature_engine(self) -> FeatureEngine:
        return FeatureEngine([RollingZScore(self.lookback)])

    def generate_signal(self, history: Sequence[Bar], features: Mapping[str, float | None]) -> ResearchSignal | None:
        z = features.get(self._feature_name)
        if z is None:
            return None
        direction = "LONG" if z <= self.entry_z else "FLAT" if z >= self.exit_z else None
        if direction is None:
            return None
        bar = history[-1]
        strength = _clip01(abs(z) / max(abs(self.entry_z) * 2, 0.5))
        return ResearchSignal(
            timestamp=bar.timestamp, symbol=bar.symbol, strategy_id=self.spec.strategy_id, strategy_version=self.spec.version,
            direction=direction, signal_strength=strength, target_position=None, feature_values=dict(features),
        )


class VolatilityRegimeStrategy(ResearchStrategy):
    """LONG when the trend is up AND volatility is in a LOW regime bucket
    (momentum is hypothesized to persist more cleanly when volatility is
    low); FLAT otherwise (including in high-volatility regimes, even if
    the trend is still nominally up)."""

    def __init__(self, *, strategy_id: str, universe: Sequence[str], fast_window: int = 10, slow_window: int = 50, vol_window: int = 20, vol_lookback: int = 100, low_vol_bucket_max: int = 1, prediction_horizon_bars: int = 5, holding_period_bars: int = 5):
        self.fast_window = fast_window
        self.slow_window = slow_window
        self.vol_window = vol_window
        self.vol_lookback = vol_lookback
        self.low_vol_bucket_max = low_vol_bucket_max
        self._trend_name = f"trend_regime_{fast_window}_{slow_window}"
        self._vol_name = f"vol_regime_{vol_window}_{vol_lookback}_5"
        self.spec = ResearchStrategySpec(
            strategy_id=strategy_id, name="Low-Volatility Trend Regime", version="1.0",
            hypothesis_id=strategy_id, universe=tuple(universe), timeframe="day",
            parameters={"fast_window": fast_window, "slow_window": slow_window, "vol_window": vol_window, "vol_lookback": vol_lookback, "low_vol_bucket_max": low_vol_bucket_max},
            holding_period_bars=holding_period_bars, prediction_horizon_bars=prediction_horizon_bars, expected_regime="low_volatility_trending",
        )

    def feature_engine(self) -> FeatureEngine:
        return FeatureEngine([TrendRegime(self.fast_window, self.slow_window), VolatilityRegime(self.vol_window, self.vol_lookback, 5)])

    def generate_signal(self, history: Sequence[Bar], features: Mapping[str, float | None]) -> ResearchSignal | None:
        trend = features.get(self._trend_name)
        vol_bucket = features.get(self._vol_name)
        if trend is None or vol_bucket is None:
            return None
        direction = "LONG" if (trend == 1.0 and vol_bucket <= self.low_vol_bucket_max) else "FLAT"
        bar = history[-1]
        # No natural single-feature magnitude to map to a strength for a
        # categorical regime signal — honestly None rather than guessed.
        return ResearchSignal(
            timestamp=bar.timestamp, symbol=bar.symbol, strategy_id=self.spec.strategy_id, strategy_version=self.spec.version,
            direction=direction, signal_strength=None, target_position=None, feature_values=dict(features),
        )


class VolumeConfirmedMomentumStrategy(ResearchStrategy):
    """LONG when trailing `lookback`-bar return exceeds `entry_threshold`
    AND relative volume exceeds `min_relative_volume` (the move is
    "confirmed" by above-average participation); FLAT otherwise."""

    def __init__(self, *, strategy_id: str, universe: Sequence[str], lookback: int = 5, entry_threshold: float = 0.02, volume_window: int = 10, min_relative_volume: float = 1.2, prediction_horizon_bars: int = 5, holding_period_bars: int = 5):
        self.lookback = lookback
        self.entry_threshold = entry_threshold
        self.volume_window = volume_window
        self.min_relative_volume = min_relative_volume
        self._roc_name = f"roc_{lookback}"
        self._vol_name = f"relative_volume_{volume_window}"
        self.spec = ResearchStrategySpec(
            strategy_id=strategy_id, name="Volume-Confirmed Momentum", version="1.0",
            hypothesis_id=strategy_id, universe=tuple(universe), timeframe="day",
            parameters={"lookback": lookback, "entry_threshold": entry_threshold, "volume_window": volume_window, "min_relative_volume": min_relative_volume},
            holding_period_bars=holding_period_bars, prediction_horizon_bars=prediction_horizon_bars, expected_regime="trending",
        )

    def feature_engine(self) -> FeatureEngine:
        return FeatureEngine([RateOfChange(self.lookback), RelativeVolume(self.volume_window)])

    def generate_signal(self, history: Sequence[Bar], features: Mapping[str, float | None]) -> ResearchSignal | None:
        roc = features.get(self._roc_name)
        rel_vol = features.get(self._vol_name)
        if roc is None or rel_vol is None:
            return None
        roc_frac = roc / 100.0
        confirmed = roc_frac > self.entry_threshold and rel_vol >= self.min_relative_volume
        direction = "LONG" if confirmed else "FLAT"
        bar = history[-1]
        strength = _clip01(abs(roc_frac) / max(self.entry_threshold * 3, 0.01)) if confirmed else None
        return ResearchSignal(
            timestamp=bar.timestamp, symbol=bar.symbol, strategy_id=self.spec.strategy_id, strategy_version=self.spec.version,
            direction=direction, signal_strength=strength, target_position=None, feature_values=dict(features),
        )


# --- companion hypotheses, written BEFORE any result is computed --------------------------


def campaign_hypotheses(universe: Sequence[str]) -> list[Hypothesis]:
    """The 6 hypotheses for this phase's first research campaign (section
    24) — written up front, on the record, before any backtest runs."""
    return [
        Hypothesis(
            hypothesis_id="MOM-001", name="5-Day Momentum", version="1.0",
            description="Strong recent positive returns may contain information about near-term continuation.",
            economic_intuition="Underreaction to news and momentum trading by other participants can cause short-term trends to persist for a few days before mean-reverting.",
            mathematical_definition="signal = 1[ROC(close, 5) > entry_threshold]; ROC(close,5) = (close[t]/close[t-5] - 1)",
            required_data=("daily OHLCV",), required_features=("roc_5",),
            prediction_horizon_bars=5, test_methodology="event-driven backtest, next-bar-open execution, train/validation/test split, walk-forward OOS aggregation",
            expected_direction="positive", assumptions=("no regime distinction", "single-asset time series, not cross-sectional"),
        ),
        Hypothesis(
            hypothesis_id="MOM-002", name="20-Day Momentum", version="1.0",
            description="Sustained positive returns over a full trading month may contain information about continued medium-term trend persistence.",
            economic_intuition="Slower-moving institutional flows and trend-following strategies can extend price moves over multi-week horizons.",
            mathematical_definition="signal = 1[ROC(close, 20) > entry_threshold]",
            required_data=("daily OHLCV",), required_features=("roc_20",),
            prediction_horizon_bars=5, test_methodology="event-driven backtest, next-bar-open execution, train/validation/test split, walk-forward OOS aggregation",
            expected_direction="positive", assumptions=("no regime distinction",),
        ),
        Hypothesis(
            hypothesis_id="MR-001", name="5-Day Short-Term Reversal", version="1.0",
            description="A sharp short-term price decline (an oversold extreme relative to its own recent distribution) tends to partially reverse.",
            economic_intuition="Short-term overreaction/liquidity-driven selling can push price temporarily below a level supported by fundamentals, correcting shortly after.",
            mathematical_definition="signal = 1[zscore(close, 5) <= entry_z]; zscore = (close[t]-mean_5)/stdev_5",
            required_data=("daily OHLCV",), required_features=("zscore_5",),
            prediction_horizon_bars=5, test_methodology="event-driven backtest, next-bar-open execution, train/validation/test split, walk-forward OOS aggregation",
            expected_direction="positive", assumptions=("reversal effect is strongest at short horizons and may not hold at longer ones",),
        ),
        Hypothesis(
            hypothesis_id="MR-002", name="20-Day Mean Reversion", version="1.0",
            description="A price that has deviated far below its own trailing 20-day distribution (z-score) tends to revert.",
            economic_intuition="Same overreaction/liquidity mechanism as MR-001, measured against a longer, smoother baseline — tests whether the effect generalizes to a slower-moving reference.",
            mathematical_definition="signal = 1[zscore(close, 20) <= entry_z]",
            required_data=("daily OHLCV",), required_features=("zscore_20",),
            prediction_horizon_bars=5, test_methodology="event-driven backtest, next-bar-open execution, train/validation/test split, walk-forward OOS aggregation",
            expected_direction="positive", assumptions=("longer lookback may dilute the short-term reversal signal MR-001 targets",),
        ),
        Hypothesis(
            hypothesis_id="VOL-001", name="Low-Volatility Trend Regime", version="1.0",
            description="An uptrend accompanied by LOW realized volatility is more likely to persist than an uptrend during high volatility.",
            economic_intuition="High volatility often reflects regime uncertainty/news-driven repricing, where trend signals are noisier and less reliable; low-volatility uptrends may reflect steadier accumulation.",
            mathematical_definition="signal = 1[trend_regime(10,50) == uptrend AND vol_regime(20,100,5) <= 1]",
            required_data=("daily OHLCV",), required_features=("trend_regime_10_50", "vol_regime_20_100_5"),
            prediction_horizon_bars=5, test_methodology="event-driven backtest, next-bar-open execution, train/validation/test split, walk-forward OOS aggregation",
            expected_direction="positive", assumptions=("regime buckets estimated from a rolling 100-bar window of realized volatility",),
        ),
        Hypothesis(
            hypothesis_id="VOLM-001", name="Volume-Confirmed Momentum", version="1.0",
            description="A positive short-term price move accompanied by above-average trading volume is more likely to be genuine/persistent than the same move on low volume.",
            economic_intuition="Volume reflects the degree of participant conviction/information flow behind a price move; low-volume moves may be noise or thin-liquidity artifacts.",
            mathematical_definition="signal = 1[ROC(close,5) > entry_threshold AND relative_volume_10 >= 1.2]",
            required_data=("daily OHLCV",), required_features=("roc_5", "relative_volume_10"),
            prediction_horizon_bars=5, test_methodology="event-driven backtest, next-bar-open execution, train/validation/test split, walk-forward OOS aggregation",
            expected_direction="positive", assumptions=("relative volume measured against the trailing 10-bar average, excluding the current bar",),
        ),
    ]
