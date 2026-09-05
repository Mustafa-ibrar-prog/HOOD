"""Phase 38, Part 5 — separating UNDERLYING EDGE from OPTION
IMPLEMENTATION EDGE.

Reuses `src.research.stats_utils.t_test_p_value` (already established in
this codebase) for the paired-difference significance test -- no new
statistical machinery invented. "Underlying went up, therefore the call
made money" is never accepted as sufficient evidence on its own: this
module measures whether the OPTION's own executable return exceeds what
the underlying's move alone would predict, on average, with real
statistical support -- never from a single aggregate number.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Sequence

from src.options.phase38_targets import ForwardOutcome
from src.research.stats_utils import t_test_p_value

MIN_SAMPLE_FOR_A_VERDICT = 20  # matches this project's established floor (src.research.placebo.MIN_BOOTSTRAP_SAMPLE, phase35_strategy_gate.MIN_TRADES_FOR_A_VERDICT)


class EdgeClassification:
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    UNDERLYING_DERIVED = "UNDERLYING_DERIVED"
    OPTION_ADDS_VALUE = "OPTION_ADDS_VALUE"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class UnderlyingVsOptionEdgeResult:
    n_outcomes: int
    mean_option_return: float | None
    mean_underlying_return: float | None
    mean_excess_return: float | None  # mean(option_minus_underlying_return_pct)
    excess_return_p_value: float | None  # paired t-test, H0: mean excess return == 0
    classification: str
    detail: str


def evaluate_underlying_vs_option_edge(
    outcomes: Sequence[ForwardOutcome], *, min_sample: int = MIN_SAMPLE_FOR_A_VERDICT, alpha: float = 0.05,
) -> UnderlyingVsOptionEdgeResult:
    usable = [o for o in outcomes if o.option_minus_underlying_return_pct is not None]
    n = len(usable)
    if n < min_sample:
        return UnderlyingVsOptionEdgeResult(
            n, None, None, None, None, EdgeClassification.INSUFFICIENT_SAMPLE,
            f"Only {n} outcome(s) with a computable underlying-vs-option comparison (< {min_sample}) -- underpowered.",
        )

    option_returns = [o.executable_return_pct for o in usable]
    underlying_returns = [o.underlying_return_pct for o in usable]
    excess_returns = [o.option_minus_underlying_return_pct for o in usable]

    mean_option = statistics.mean(option_returns)
    mean_underlying = statistics.mean(underlying_returns)
    mean_excess = statistics.mean(excess_returns)
    p_value = t_test_p_value(excess_returns, null_mean=0.0)

    if mean_excess <= 0:
        classification = EdgeClassification.UNDERLYING_DERIVED
        detail = f"Mean excess return over the underlying is not positive (${mean_excess:.4f}) -- any apparent edge is explained by the underlying's own move."
    elif p_value is not None and p_value < alpha:
        classification = EdgeClassification.OPTION_ADDS_VALUE
        detail = f"Mean excess return {mean_excess:.4f} is positive and statistically distinguishable from zero (p={p_value:.4f})."
    else:
        classification = EdgeClassification.INCONCLUSIVE
        detail = f"Mean excess return {mean_excess:.4f} is positive but not statistically distinguishable from zero (p={p_value})."

    return UnderlyingVsOptionEdgeResult(n, mean_option, mean_underlying, mean_excess, p_value, classification, detail)
