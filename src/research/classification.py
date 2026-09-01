"""Research classification (Phase 4, section 17).

Deliberately rule-based and NOT a single opaque score — every
classification comes with the specific reasons that produced it, so a
human reviewing a PROMISING result can see exactly what was checked, not
just trust a number. These are RESEARCH classifications, not guarantees of
future profitability, and (section 22) a PROMISING classification has no
code path anywhere in this codebase to automatic paper or live trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.backtesting.metrics import PerformanceMetrics
from src.research.sweep import ParameterStabilityReport
from src.research.validation import CostSensitivityReport, RobustnessReport


class StrategyClassification(str, Enum):
    PROMISING = "PROMISING"
    INCONCLUSIVE = "INCONCLUSIVE"
    FRAGILE = "FRAGILE"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class ClassificationResult:
    classification: StrategyClassification
    reasons: tuple[str, ...]


# Minimum OOS trade count before ANY conclusion is drawn — below this,
# the honest answer is "not enough evidence," never a REJECTED/PROMISING
# call based on statistical noise.
MIN_OOS_TRADES_FOR_A_VERDICT = 20


def classify_strategy(
    *,
    oos_metrics: PerformanceMetrics,
    in_sample_metrics: PerformanceMetrics | None = None,
    parameter_stability: ParameterStabilityReport | None = None,
    cost_sensitivity: CostSensitivityReport | None = None,
    robustness: RobustnessReport | None = None,
    min_oos_sharpe_or_expectancy: float = 0.0,
) -> ClassificationResult:
    reasons: list[str] = []
    oos_trade_count = oos_metrics.trades.trade_count

    if oos_trade_count < MIN_OOS_TRADES_FOR_A_VERDICT:
        reasons.append(f"only {oos_trade_count} out-of-sample trades (< {MIN_OOS_TRADES_FOR_A_VERDICT} minimum) — insufficient evidence to draw a conclusion either way")
        return ClassificationResult(StrategyClassification.INCONCLUSIVE, tuple(reasons))

    oos_expectancy = oos_metrics.trades.expectancy
    oos_positive = oos_expectancy > 0

    if not oos_positive:
        reasons.append(f"out-of-sample expectancy is non-positive (${oos_expectancy:.2f}/trade)")
    if oos_metrics.trades.profit_factor is not None and oos_metrics.trades.profit_factor < 1.0:
        reasons.append(f"out-of-sample profit factor below 1.0 ({oos_metrics.trades.profit_factor:.2f})")

    if not oos_positive:
        return ClassificationResult(StrategyClassification.REJECTED, tuple(reasons) or ("no evidence of a positive out-of-sample edge",))

    fragility_reasons: list[str] = []
    if in_sample_metrics is not None:
        is_exp = in_sample_metrics.trades.expectancy
        # A large in-sample-vs-OOS gap (IS looks much better than OOS) is
        # the classic overfitting signature.
        if is_exp > 0 and oos_expectancy < is_exp * 0.3:
            fragility_reasons.append(f"in-sample expectancy (${is_exp:.2f}) far exceeds out-of-sample (${oos_expectancy:.2f}) — a classic overfitting signature")

    if parameter_stability is not None and parameter_stability.is_broadly_acceptable is False:
        fragility_reasons.append(f"only {(parameter_stability.fraction_acceptable or 0):.0%} of the parameter grid cleared the acceptability threshold — highly parameter-sensitive")

    if cost_sensitivity is not None and cost_sensitivity.viable_at_base and cost_sensitivity.viable_at_2x is False:
        fragility_reasons.append("strategy is profitable at modeled (1x) costs but fails at 2x transaction costs")

    if robustness is not None and robustness.fraction_held is not None and robustness.fraction_held < 0.5:
        fragility_reasons.append(f"only {robustness.fraction_held:.0%} of robustness checks held")

    if fragility_reasons:
        return ClassificationResult(StrategyClassification.FRAGILE, tuple(fragility_reasons))

    promising_reasons = [
        f"positive out-of-sample expectancy (${oos_expectancy:.2f}/trade over {oos_trade_count} trades)",
    ]
    if cost_sensitivity is not None:
        promising_reasons.append(f"remains viable at 2x costs: {cost_sensitivity.viable_at_2x}")
    if parameter_stability is not None and parameter_stability.is_broadly_acceptable:
        promising_reasons.append(f"broadly stable across the tested parameter grid ({(parameter_stability.fraction_acceptable or 0):.0%} acceptable)")
    if robustness is not None and robustness.fraction_held is not None:
        promising_reasons.append(f"{robustness.fraction_held:.0%} of robustness checks held")

    return ClassificationResult(StrategyClassification.PROMISING, tuple(promising_reasons))
