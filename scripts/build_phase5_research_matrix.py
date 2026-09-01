#!/usr/bin/env python3
"""Builds and prints the Phase 5, section-17 research matrix from the
evidence gathered during the campaign runs. This is a reporting script
only — it does not re-run any backtests; the figures it hard-codes below
are transcribed directly from scripts/run_research_campaign_phase5.py's
and scripts/finish_phase5_vol_volm.py's logged output for the
US_DIVERSIFIED universe run. Row order == hypothesis order from Phase 4;
never sorted by performance.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.research.classification import ClassificationResult, StrategyClassification
from src.research.research_matrix import ResearchMatrix, ResearchMatrixRow

rows = [
    ResearchMatrixRow(
        hypothesis_id="MOM-001", strategy_name="5-day momentum",
        is_evidence="286 trades, net_pnl=$2,331.64, sharpe=0.16",
        validation_evidence="wide param sweep: 7 combos, 57% acceptable, mean expectancy $7.18/stdev $12.01",
        oos_evidence="93 trades, win_rate=31.18%, expectancy=$4.04/trade, profit_factor=1.05",
        parameter_stability="57% of grid acceptable — moderate sensitivity",
        time_stability="2022 strongly negative (-$6,591/149 trades); other years mixed/small",
        universe_stability="n/a (single universe tested this phase for this metric)",
        regime_stability="bear_high_vol worst (-$43.97/trade); bear_low_vol best (+$96.39/trade) — regime dependent",
        cost_sensitivity="viable at 1x only; fails at 2x and 3x costs",
        execution_sensitivity="fraction_viable=0.5 (fails under +1 bar delay and 2x slippage)",
        placebo_bootstrap_evidence="placebo fraction_as_extreme_or_better=0.50 (not distinguishable from randomized-entry baseline); bootstrap 90% CI [-49.02, 66.99] includes zero",
        sample_size=93,
        known_biases=("current-constituent/survivorship-biased universe",),
        limitations=("leave-one-out sign flips on TSLA/UNH removal",),
        classification=ClassificationResult(StrategyClassification.FRAGILE, (
            "only 57% of the parameter grid cleared the acceptability threshold — highly parameter-sensitive",
            "strategy is profitable at modeled (1x) costs but fails at 2x transaction costs",
        )),
    ),
    ResearchMatrixRow(
        hypothesis_id="MOM-002", strategy_name="20-day momentum",
        is_evidence="152 trades, net_pnl=$319.88, sharpe=0.04",
        validation_evidence="wide param sweep: 8 combos, 75% acceptable, mean expectancy $10.39/stdev $36.58",
        oos_evidence="80 trades, win_rate=41.25%, expectancy=$1.17/trade, profit_factor=1.01",
        parameter_stability="75% of grid acceptable, but wide dispersion (stdev $36.58 vs mean $10.39)",
        time_stability="2022 strongly negative (-$5,019/66 trades)",
        universe_stability="n/a (single universe tested this phase for this metric)",
        regime_stability="bear_high_vol worst (-$80.41/trade)",
        cost_sensitivity="viable at 1x only; fails at 2x and 3x costs",
        execution_sensitivity="fraction_viable=0.5 (fails under +1 bar delay and 2x slippage)",
        placebo_bootstrap_evidence="placebo fraction_as_extreme_or_better=0.64; bootstrap 90% CI [-60.83, 67.46] includes zero",
        sample_size=80,
        known_biases=("current-constituent/survivorship-biased universe",),
        limitations=("leave-one-out sign flips on CAT/CVX/UNH removal", "UNH alone contributes 8x the total net P&L — heavy concentration"),
        classification=ClassificationResult(StrategyClassification.FRAGILE, (
            "strategy is profitable at modeled (1x) costs but fails at 2x transaction costs",
        )),
    ),
    ResearchMatrixRow(
        hypothesis_id="MR-001", strategy_name="5-day mean reversion",
        is_evidence="500 trades, net_pnl=$4,369.64, sharpe=0.27",
        validation_evidence="wide param sweep: 7 combos, 43% acceptable, mean expectancy $2.56/stdev $4.85",
        oos_evidence="207 trades, win_rate=64.25%, expectancy=$19.87/trade, profit_factor=1.29",
        parameter_stability="only 43% of grid acceptable — highly parameter-sensitive",
        time_stability="2022 negative (-$1,972/200 trades); other years mostly positive",
        universe_stability="n/a (single universe tested this phase for this metric)",
        regime_stability="bull_high_vol best (+$27.70/trade); bear_low_vol worst (-$14.28/trade)",
        cost_sensitivity="viable at 1x only; fails at 2x and 3x costs",
        execution_sensitivity="fraction_viable=0.75 (fails only under +1 bar delay)",
        placebo_bootstrap_evidence="placebo fraction_as_extreme_or_better=0.31; bootstrap 90% CI [-21.93, 55.62] includes zero",
        sample_size=207,
        known_biases=("current-constituent/survivorship-biased universe",),
        limitations=("leave-one-out sign flip on TSLA removal alone", "TSLA alone contributes 118% of net P&L — single-symbol concentration"),
        classification=ClassificationResult(StrategyClassification.FRAGILE, (
            "only 43% of the parameter grid cleared the acceptability threshold — highly parameter-sensitive",
            "strategy is profitable at modeled (1x) costs but fails at 2x transaction costs",
        )),
    ),
    ResearchMatrixRow(
        hypothesis_id="MR-002", strategy_name="20-day mean reversion",
        is_evidence="410 trades, net_pnl=$11,662.84, sharpe=0.42 (US_DIVERSIFIED); by contrast IS net_pnl=-$479.87 on the original US_SMALL_CAP_VOLATILE universe (see section-18 investigation)",
        validation_evidence="wide param sweep: 8 combos, 88% acceptable, mean expectancy $25.02/stdev $14.54; narrow neighborhood [15,18,20,22,25]: 100% acceptable, monotonically increasing with lookback",
        oos_evidence="210 trades, win_rate=70.95%, expectancy=$52.91/trade, profit_factor=1.77",
        parameter_stability="88% of wide grid acceptable; 100% of narrow neighborhood acceptable — broadly stable",
        time_stability="positive in 5 of 6 years; only 2022 negative (-$1,187/129 trades)",
        universe_stability="INVERTS across universes: FRAGILE/negative-IS on the original 5-symbol universe, PROMISING on the 20-symbol diversified universe — see section-18 finding",
        regime_stability="positive in bull_high_vol, bear_high_vol, bull_low_vol; only bear_low_vol negative (-$16.80/trade)",
        cost_sensitivity="viable at 1x, 2x, AND 3x costs",
        execution_sensitivity="fraction_viable=1.0 (viable under base, +1 bar delay, 2x slippage, and 2x costs)",
        placebo_bootstrap_evidence="placebo fraction_as_extreme_or_better=0.04 (only 4% of randomized-entry trials matched or beat the observed result); bootstrap 90% CI [14.49, 90.75] EXCLUDES zero",
        sample_size=210,
        known_biases=("current-constituent/survivorship-biased universe", "multiple-hypothesis testing across 6 hypotheses x 2 universes without formal correction"),
        limitations=(
            "leave-one-out: zero sign flips, no single symbol required for a positive result",
            "still only ~5 years of daily data / one full market cycle",
            "not yet tested walk-forward on a third, independent universe",
        ),
        classification=ClassificationResult(StrategyClassification.PROMISING, (
            "positive out-of-sample expectancy ($52.91/trade over 210 trades)",
            "remains viable at 2x costs: True",
            "broadly stable across the tested parameter grid (88% acceptable)",
        )),
    ),
    ResearchMatrixRow(
        hypothesis_id="VOL-001", strategy_name="low-volatility trend regime",
        is_evidence="208 trades, net_pnl=-$10,342.59, sharpe=-0.65",
        validation_evidence="wide param sweep: 5 combos, 20% acceptable, mean expectancy -$12.83/stdev $27.51",
        oos_evidence="89 trades, win_rate=55.06%, expectancy=$95.48/trade, profit_factor=2.39 — a large positive OOS number that contradicts a clearly negative IS result",
        parameter_stability="only 20% of grid acceptable — highly parameter-sensitive",
        time_stability="negative in 5 of 6 years (2023 the lone exception at +$386)",
        universe_stability="n/a (single universe tested this phase for this metric)",
        regime_stability="bear_high_vol worst (-$110.95/trade)",
        cost_sensitivity="NOT viable at 1x, 2x, or 3x costs",
        execution_sensitivity="fraction_viable=0.0 (fails every execution-stress scenario, including base)",
        placebo_bootstrap_evidence="placebo fraction_as_extreme_or_better=0.01; bootstrap 90% CI [33.62, 164.71] excludes zero, but this conflicts with the failing cost/execution/IS evidence — treated as an OOS-window artifact, not evidence of a real edge",
        sample_size=89,
        known_biases=("current-constituent/survivorship-biased universe",),
        limitations=("IS and cost/execution evidence directly contradict the OOS headline number — a textbook case for why OOS expectancy alone is not sufficient",),
        classification=ClassificationResult(StrategyClassification.FRAGILE, (
            "only 20% of the parameter grid cleared the acceptability threshold — highly parameter-sensitive",
        )),
    ),
    ResearchMatrixRow(
        hypothesis_id="VOLM-001", strategy_name="volume-confirmed momentum",
        is_evidence="120 trades, net_pnl=-$1,802.83, sharpe=-0.80",
        validation_evidence="wide param sweep: 7 combos, 14% acceptable, mean expectancy -$9.07 (all but one value negative)",
        oos_evidence="32 trades, win_rate=40.62%, expectancy=$18.90/trade, profit_factor=1.53",
        parameter_stability="only 14% of grid acceptable — highly parameter-sensitive",
        time_stability="negative in 4 of 6 years",
        universe_stability="n/a (single universe tested this phase for this metric)",
        regime_stability="bull_low_vol worst (-$44.83/trade); bear_low_vol best (+$18.96/trade)",
        cost_sensitivity="NOT viable at 1x, 2x, or 3x costs",
        execution_sensitivity="fraction_viable=0.25 (viable only under one scenario)",
        placebo_bootstrap_evidence="placebo fraction_as_extreme_or_better=0.40; bootstrap 90% CI [-23.62, 71.20] includes zero; n=32 is close to the MIN_OOS_TRADES_FOR_A_VERDICT=20 floor",
        sample_size=32,
        known_biases=("current-constituent/survivorship-biased universe",),
        limitations=("small OOS sample (32 trades) limits confidence in any conclusion",),
        classification=ClassificationResult(StrategyClassification.FRAGILE, (
            "only 14% of the parameter grid cleared the acceptability threshold — highly parameter-sensitive",
        )),
    ),
]

matrix = ResearchMatrix(rows=tuple(rows))
print(matrix.render())
