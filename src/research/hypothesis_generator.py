"""Phase 7, Part 12: a controlled hypothesis generator.

NOT an unrestricted optimizer — this module NEVER selects parameters
based on any result. It returns a FIXED list of hypotheses, each drawn
from a predefined, economically motivated mechanism family, each with one
deliberately chosen (not searched-for) parameterization. A future
robustness/parameter-stability check on any ONE of these hypotheses
belongs to a LATER research stage (src.research.sweep,
src.research.validation), not here.

Every generated Hypothesis is a real src.research.hypothesis.Hypothesis
(Phase 4's registry type, extended additively in Phase 7) — this module
does not invent a parallel schema.
"""

from __future__ import annotations

from enum import Enum
from typing import Sequence

from src.research.hypothesis import Hypothesis


class HypothesisFamily(str, Enum):
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    VOLATILITY = "volatility"
    VOLUME_PRICE_CONFIRMATION = "volume_price_confirmation"
    TREND_PERSISTENCE = "trend_persistence"
    VOLATILITY_BREAKOUT = "volatility_breakout"
    CROSS_SECTIONAL_RELATIVE_STRENGTH = "cross_sectional_relative_strength"
    MARKET_RELATIVE = "market_relative"
    SECTOR_RELATIVE = "sector_relative"
    VOLATILITY_ADJUSTED_MOMENTUM = "volatility_adjusted_momentum"
    VOLUME_ANOMALY = "volume_anomaly"
    GAP_REVERSAL = "gap_reversal"


def generate_hypotheses(universe: Sequence[str], *, benchmark_symbol: str = "SPY") -> list[Hypothesis]:
    """Returns exactly 12 hypotheses, one per HypothesisFamily member —
    breadth of mechanism over parameter variation, per Part 14's explicit
    instruction. Every parameter below (lookback, threshold, horizon) is a
    single, reasonable, PRE-CHOSEN value — never a grid, never tuned."""
    universe = tuple(universe)
    return [
        Hypothesis(
            hypothesis_id="P7-MOM-A", name="20-day momentum (Phase 7 discovery)", version="1.0",
            description="Recent 20-day price strength predicts continued near-term outperformance.",
            economic_intuition="Underreaction to information and trend-following flows can extend a price move for some period before mean-reverting.",
            mathematical_definition="feature = ROC(close, 20) = close[t]/close[t-20] - 1; target = future_return(5)",
            required_data=("daily OHLCV",), required_features=("roc_20",), prediction_horizon_bars=5,
            test_methodology="cross-sectional IC/quantile analysis on DISCOVERY_DATA only — no backtest at this stage",
            expected_direction="positive", assumptions=("no regime distinction at the discovery stage",),
            family=HypothesisFamily.MOMENTUM.value, target_definition="target_future_return_5bar",
            holding_period_bars=5, entry_rule="LONG top-quantile ROC(20)", exit_rule="after holding_period_bars",
            universe=universe, expected_mechanism="trend continuation from underreaction/momentum-chasing flows",
            falsification_criteria=("IC not reliably positive across DISCOVERY_DATA", "quantile spread not monotonic", "effect does not survive shuffled-signal placebo"),
        ),
        Hypothesis(
            hypothesis_id="P7-MR-A", name="20-day mean reversion (Phase 7 discovery)", version="1.0",
            description="A price far below its own trailing 20-day distribution tends to partially revert.",
            economic_intuition="Short-term overreaction and liquidity-driven selling can push price below a level fundamentals support, correcting shortly after.",
            mathematical_definition="feature = zscore(close, 20); target = future_return(5)",
            required_data=("daily OHLCV",), required_features=("zscore_20",), prediction_horizon_bars=5,
            test_methodology="cross-sectional IC/quantile analysis on DISCOVERY_DATA only",
            expected_direction="negative", assumptions=("reversal, if real, may be strongest at short horizons",),
            family=HypothesisFamily.MEAN_REVERSION.value, target_definition="target_future_return_5bar",
            holding_period_bars=5, entry_rule="LONG bottom-quantile zscore(20)", exit_rule="after holding_period_bars",
            universe=universe, expected_mechanism="overreaction/liquidity-driven selling correcting toward a slower-moving fair value",
            falsification_criteria=("IC not reliably negative", "quantile spread not monotonic", "effect does not survive shuffled-signal placebo"),
        ),
        Hypothesis(
            hypothesis_id="P7-VOL-A", name="low realized volatility predicts calmer, positive drift (Phase 7 discovery)", version="1.0",
            description="A currently LOW realized-volatility regime predicts more positive near-term drift than a high-volatility regime.",
            economic_intuition="High realized volatility often reflects unresolved uncertainty/news risk, historically associated with lower average forward returns (a volatility risk premium effect).",
            mathematical_definition="feature = -RealizedVolatility(20) [feature name: realized_vol_20] (sign-flipped so 'low vol' scores high); target = future_return(10)",
            required_data=("daily OHLCV",), required_features=("realized_vol_20",), prediction_horizon_bars=10,
            test_methodology="cross-sectional IC/quantile analysis on DISCOVERY_DATA only",
            expected_direction="positive", assumptions=("volatility risk premium is treated as a cross-sectional effect here, not a market-timing one",),
            family=HypothesisFamily.VOLATILITY.value, target_definition="target_future_return_10bar",
            holding_period_bars=10, entry_rule="LONG lowest-volatility quantile", exit_rule="after holding_period_bars",
            universe=universe, expected_mechanism="volatility risk premium / uncertainty discount",
            falsification_criteria=("IC not reliably positive", "effect concentrated in one narrow regime only"),
        ),
        Hypothesis(
            hypothesis_id="P7-VPC-A", name="volume-confirmed momentum (Phase 7 discovery)", version="1.0",
            description="A positive price move accompanied by above-average volume is more informative than the same move on ordinary volume.",
            economic_intuition="Volume reflects the degree of participant conviction/information flow behind a price move.",
            mathematical_definition="feature = ROC(close, 5) * RelativeVolume(10)  (a simple interaction term computed in-script from two existing features); target = future_return(5)",
            required_data=("daily OHLCV",), required_features=("roc_5", "relative_volume_10"), prediction_horizon_bars=5,
            test_methodology="cross-sectional IC/quantile analysis on DISCOVERY_DATA only",
            expected_direction="positive", assumptions=("relative volume measured against the trailing 10-bar average",),
            family=HypothesisFamily.VOLUME_PRICE_CONFIRMATION.value, target_definition="target_future_return_5bar",
            holding_period_bars=5, entry_rule="LONG top-quantile of ROC(5)*RelativeVolume(10)", exit_rule="after holding_period_bars",
            universe=universe, expected_mechanism="volume-confirmed moves reflect genuine conviction rather than thin-liquidity noise",
            falsification_criteria=("IC not reliably positive", "no improvement in IC over plain momentum alone (random_feature_control / irrelevant_feature_control comparison)"),
        ),
        Hypothesis(
            hypothesis_id="P7-TREND-A", name="trend-regime persistence (Phase 7 discovery)", version="1.0",
            description="Being currently classified in an uptrend (via the existing causal TrendRegime feature) predicts continued positive near-term drift.",
            economic_intuition="Trends, once established, are more likely than not to persist over the near term due to slow-moving capital flows and anchoring.",
            mathematical_definition="feature = TrendRegime(10, 50) numeric label (+1/0/-1); target = future_return(10)",
            required_data=("daily OHLCV",), required_features=("trend_regime_10_50",), prediction_horizon_bars=10,
            test_methodology="cross-sectional IC/quantile analysis on DISCOVERY_DATA only",
            expected_direction="positive", assumptions=("uses the SAME causal TrendRegime feature already relied on elsewhere in this codebase",),
            family=HypothesisFamily.TREND_PERSISTENCE.value, target_definition="target_future_return_10bar",
            holding_period_bars=10, entry_rule="LONG when TrendRegime == uptrend", exit_rule="after holding_period_bars",
            universe=universe, expected_mechanism="trend persistence from slow capital reallocation",
            falsification_criteria=("IC not reliably positive", "effect indistinguishable from a simple momentum feature already tested"),
        ),
        Hypothesis(
            hypothesis_id="P7-BRK-A", name="volatility compression precedes larger moves (Phase 7 discovery)", version="1.0",
            description="A period of unusually LOW realized volatility (compression) is followed by a larger-than-usual subsequent move (in EITHER direction).",
            economic_intuition="Volatility compression often reflects a build-up of unresolved directional pressure that eventually resolves via a breakout.",
            mathematical_definition="feature = -VolatilityPercentile(20,100) (low percentile scores high); target = |future_return(10)|  (MAGNITUDE, not sign — this hypothesis is about the SIZE of the subsequent move, not its direction)",
            required_data=("daily OHLCV",), required_features=("vol_percentile_20_100",), prediction_horizon_bars=10,
            test_methodology="cross-sectional IC/quantile analysis on |target| on DISCOVERY_DATA only",
            expected_direction="positive", assumptions=("tests magnitude, not direction — a fundamentally different claim from the directional hypotheses above",),
            family=HypothesisFamily.VOLATILITY_BREAKOUT.value, target_definition="abs(target_future_return_10bar)",
            holding_period_bars=10, entry_rule="not directional — would require a straddle-like structure to trade, out of scope for a discovery-stage IC test", exit_rule="after holding_period_bars",
            universe=universe, expected_mechanism="volatility compression as a precursor to breakout",
            falsification_criteria=("IC (vs |return|) not reliably positive", "compression predicts smaller, not larger, subsequent moves"),
        ),
        Hypothesis(
            hypothesis_id="P7-XSEC-A", name="cross-sectional relative strength (Phase 7 discovery)", version="1.0",
            description="A symbol's momentum RELATIVE TO the universe's own cross-sectional average momentum predicts relative outperformance.",
            economic_intuition="Relative strength within a peer group can reflect idiosyncratic information not explained by common/systematic moves.",
            mathematical_definition="feature = ROC(close,20) - cross_sectional_mean(ROC(close,20)) at the same timestamp (computed in-script, demeaning the existing roc_20 feature per timestamp); target = future_return(5)",
            required_data=("daily OHLCV",), required_features=("roc_20",), prediction_horizon_bars=5,
            test_methodology="cross-sectional IC/quantile analysis on a per-timestamp demeaned feature, DISCOVERY_DATA only",
            expected_direction="positive", assumptions=("demeaning removes any pure market-wide component from plain momentum",),
            family=HypothesisFamily.CROSS_SECTIONAL_RELATIVE_STRENGTH.value, target_definition="target_future_return_5bar",
            holding_period_bars=5, entry_rule="LONG top-quantile of universe-demeaned ROC(20)", exit_rule="after holding_period_bars",
            universe=universe, expected_mechanism="idiosyncratic relative strength distinct from market-wide momentum",
            falsification_criteria=("IC not reliably positive", "no improvement over plain (non-demeaned) momentum's IC"),
        ),
        Hypothesis(
            hypothesis_id="P7-MKTREL-A", name="market-relative momentum (Phase 7 discovery)", version="1.0",
            description=f"A symbol's return relative to the {benchmark_symbol} benchmark's return over the same window predicts continued relative outperformance.",
            economic_intuition="Excess return over a benchmark isolates idiosyncratic strength from beta/market-wide moves.",
            mathematical_definition=f"feature = ROC(close,20) - ROC({benchmark_symbol}_close,20) (computed in-script, subtracting the benchmark's own ROC at the same timestamp); target = future_return(5)",
            required_data=("daily OHLCV",), required_features=("roc_20",), prediction_horizon_bars=5,
            test_methodology="cross-sectional IC/quantile analysis on a market-relative feature, DISCOVERY_DATA only",
            expected_direction="positive", assumptions=(f"{benchmark_symbol} is treated as the market proxy",),
            family=HypothesisFamily.MARKET_RELATIVE.value, target_definition="target_future_return_5bar",
            holding_period_bars=5, entry_rule=f"LONG top-quantile of ROC(20) minus {benchmark_symbol}'s ROC(20)", exit_rule="after holding_period_bars",
            universe=universe, expected_mechanism="idiosyncratic strength net of market-wide beta",
            falsification_criteria=("IC not reliably positive", "no improvement over the plain (non-market-relative) momentum hypothesis"),
        ),
        Hypothesis(
            hypothesis_id="P7-SECTREL-A", name="sector-relative momentum (Phase 7 discovery)", version="1.0",
            description="A symbol's momentum RELATIVE TO its own sector's average momentum predicts relative outperformance within that sector.",
            economic_intuition="Sector-relative strength can reflect company-specific information distinct from sector-wide rotation.",
            mathematical_definition="feature = ROC(close,20) - sector_mean(ROC(close,20)) at the same timestamp, computed in-script using the sector labels from the Universe object; target = future_return(5)",
            required_data=("daily OHLCV", "universe sector labels"), required_features=("roc_20",), prediction_horizon_bars=5,
            test_methodology="cross-sectional IC/quantile analysis on a sector-demeaned feature, DISCOVERY_DATA only, requires a Universe with sector data",
            expected_direction="positive", assumptions=("only meaningful if the universe carries usable sector labels — see src.data.universe.Universe.by_sector()",),
            family=HypothesisFamily.SECTOR_RELATIVE.value, target_definition="target_future_return_5bar",
            holding_period_bars=5, entry_rule="LONG top-quantile of sector-demeaned ROC(20)", exit_rule="after holding_period_bars",
            universe=universe, expected_mechanism="company-specific relative strength within a sector, distinct from sector-wide rotation",
            falsification_criteria=("IC not reliably positive", "no improvement over the plain (non-sector-relative) momentum hypothesis", "insufficient sector diversity in the universe to test at all"),
        ),
        Hypothesis(
            hypothesis_id="P7-VOLADJMOM-A", name="volatility-adjusted momentum (Phase 7 discovery)", version="1.0",
            description="Momentum scaled by its own recent volatility (a risk-adjusted momentum score) predicts near-term returns better than raw momentum.",
            economic_intuition="A given price move means more (higher conviction, less noise) when realized in a low-volatility environment than in a high-volatility one.",
            mathematical_definition="feature = ROC(close,20) / RealizedVolatility(20) [feature name: realized_vol_20] (computed in-script from two existing features); target = future_return(5)",
            required_data=("daily OHLCV",), required_features=("roc_20", "realized_vol_20"), prediction_horizon_bars=5,
            test_methodology="cross-sectional IC/quantile analysis on a risk-adjusted feature, DISCOVERY_DATA only",
            expected_direction="positive", assumptions=("division is guarded against zero/near-zero volatility",),
            family=HypothesisFamily.VOLATILITY_ADJUSTED_MOMENTUM.value, target_definition="target_future_return_5bar",
            holding_period_bars=5, entry_rule="LONG top-quantile of ROC(20)/RealizedVolatility(20) [feature name: realized_vol_20]", exit_rule="after holding_period_bars",
            universe=universe, expected_mechanism="risk-adjusting momentum removes noise from high-volatility names' raw price moves",
            falsification_criteria=("IC not reliably positive", "no improvement over plain (non-risk-adjusted) momentum's IC"),
        ),
        Hypothesis(
            hypothesis_id="P7-VOLANOM-A", name="volume anomaly (Phase 7 discovery)", version="1.0",
            description="Unusually high trading volume alone (independent of price direction) predicts subsequent volatility/return magnitude.",
            economic_intuition="A volume spike often signals new information entering the market, which the price may not yet fully reflect.",
            mathematical_definition="feature = RelativeVolume(10); target = |future_return(5)|  (MAGNITUDE, not sign — a volume spike is not hypothesized to predict DIRECTION on its own)",
            required_data=("daily OHLCV",), required_features=("relative_volume_10",), prediction_horizon_bars=5,
            test_methodology="cross-sectional IC/quantile analysis on |target|, DISCOVERY_DATA only",
            expected_direction="positive", assumptions=("tests magnitude, not direction, same distinction as the volatility-breakout hypothesis above",),
            family=HypothesisFamily.VOLUME_ANOMALY.value, target_definition="abs(target_future_return_5bar)",
            holding_period_bars=5, entry_rule="not directional — informational only at the discovery stage", exit_rule="after holding_period_bars",
            universe=universe, expected_mechanism="volume spikes precede information-driven volatility",
            falsification_criteria=("IC (vs |return|) not reliably positive",),
        ),
        Hypothesis(
            hypothesis_id="P7-GAP-A", name="overnight gap reversal (Phase 7 discovery)", version="1.0",
            description="A large overnight gap (open far from the prior close) tends to partially reverse during the following session(s).",
            economic_intuition="Overnight gaps often reflect an overreaction to after-hours news/order imbalance that partially corrects once regular-session liquidity returns.",
            mathematical_definition="feature = (open[t] - close[t-1]) / close[t-1]  (a simple gap computed directly from bar data in-script — no dedicated Feature class exists for this yet); target = future_return(5), measured from open[t]",
            required_data=("daily OHLCV",), required_features=(), prediction_horizon_bars=5,
            test_methodology="cross-sectional IC/quantile analysis on a script-computed gap feature, DISCOVERY_DATA only",
            expected_direction="negative", assumptions=("gap direction and reversal are treated as a linear relationship for the discovery-stage IC test",),
            family=HypothesisFamily.GAP_REVERSAL.value, target_definition="target_future_return_5bar",
            holding_period_bars=5, entry_rule="LONG bottom-quantile gap (large negative gap), SHORT top-quantile gap (large positive gap)", exit_rule="after holding_period_bars",
            universe=universe, expected_mechanism="overnight overreaction correcting once regular-session liquidity returns",
            falsification_criteria=("IC not reliably negative", "effect does not survive shuffled-signal placebo"),
        ),
    ]
