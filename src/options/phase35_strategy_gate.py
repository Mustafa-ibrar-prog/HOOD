"""Phase 35, Part M/T — the Strategy Gate classification.

Part M requires reusing the project's established evidence vocabulary
(`VALIDATED_CANDIDATE, PROMISING, TRADEABLE_SIGNAL_FRAGILE,
INHERITED_FROM_UNDERLYING, REJECTED, INCONCLUSIVE, NOT_READY,
DATA_LIMITED`) but the existing `phase31_classification.HypothesisEvidence`/
`phase31_gate.evaluate_gate` are built entirely around cross-sectional
IC/quantile-portfolio machinery (average_ic, quantile_spread, symbol-
cluster IC-bootstrap) that a trade-list-based strategy backtest simply
does not produce (confirmed by direct inspection this phase -- a
strategy has entry/exit prices and P&L per closed trade, evaluated via
Sharpe/expectancy/profit-factor/drawdown, never an IC). Forcing
`BacktestTrade` sequences into that shape would mean leaving most fields
perpetually None or fabricating a fake cross-section -- exactly what
this project's own established convention (see
`src.backtesting.journal`'s module docstring on why it does NOT reuse
`src.logging.trade_journal.TradeJournal`'s option-shaped record for
equity trades) says never to do.

So THIS module mirrors the 12-criterion gate's STRUCTURE (explicit,
numeric, disclosed criteria; never a bare p<0.05; "if nothing qualifies,
that is a valid result") using the trade-list-native evidence this phase
actually produced (bootstrap CI, cost-stress survival, placebo empirical
p-value, leave-one-symbol/period-out, outlier dependence, underlying-vs-
option comparison, affordability) -- the SAME vocabulary, a fresh,
honestly-documented set of criteria for a genuinely different evidence
shape, never a weaker or additional category.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

MIN_TRADES_FOR_A_VERDICT = 20  # matches src.research.placebo.MIN_BOOTSTRAP_SAMPLE -- the same "enough sample to say anything" floor this project already uses


class StrategyClassification(str, Enum):
    VALIDATED_CANDIDATE = "VALIDATED_CANDIDATE"
    PROMISING = "PROMISING"
    TRADEABLE_SIGNAL_FRAGILE = "TRADEABLE_SIGNAL_FRAGILE"
    INHERITED_FROM_UNDERLYING = "INHERITED_FROM_UNDERLYING"
    REJECTED = "REJECTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_READY = "NOT_READY"
    DATA_LIMITED = "DATA_LIMITED"


@dataclass(frozen=True)
class GateCriterionResult:
    number: int
    name: str
    passed: bool | None  # None when not applicable/not evaluated
    detail: str


@dataclass(frozen=True)
class StrategyGateEvidence:
    n_trades: int
    mean_net_pnl: float | None
    bootstrap_excludes_zero_90pct: bool | None  # BootstrapReport.mean_trade_return_ci or expectancy_ci, lower bound > 0
    cost_survives_1x: bool | None
    cost_survives_2x: bool | None
    cost_survives_3x: bool | None
    cost_survives_5x: bool | None
    placebo_empirical_p: float | None
    outlier_dependent: bool | None  # top-1% trades explain > 50% of positive P&L
    leave_one_symbol_out_all_positive: bool | None  # excluding any one symbol never flips mean_net_pnl negative
    leave_one_period_out_all_positive: bool | None  # same, for years
    pct_trades_affordable_1000usd: float | None
    underlying_only_edge_present: bool | None  # does the underlying itself show a comparable or better mean return over the same windows?
    option_adds_value_after_costs: bool | None  # option net P&L outperforms the underlying-only comparison after the SAME cost stress


def classify_strategy(evidence: StrategyGateEvidence) -> tuple[StrategyClassification, str, tuple[GateCriterionResult, ...]]:
    criteria: list[GateCriterionResult] = []

    if evidence.n_trades < MIN_TRADES_FOR_A_VERDICT:
        criteria.append(GateCriterionResult(1, "sufficient_sample", False, f"n_trades={evidence.n_trades} < {MIN_TRADES_FOR_A_VERDICT}"))
        return (
            StrategyClassification.NOT_READY,
            f"Only {evidence.n_trades} real matched trades (< {MIN_TRADES_FOR_A_VERDICT}) -- underpowered, not classifiable either way.",
            tuple(criteria),
        )
    criteria.append(GateCriterionResult(1, "sufficient_sample", True, f"n_trades={evidence.n_trades} >= {MIN_TRADES_FOR_A_VERDICT}"))

    if evidence.underlying_only_edge_present and evidence.option_adds_value_after_costs is False:
        criteria.append(GateCriterionResult(2, "not_explained_by_underlying", False, "Underlying alone shows a comparable/better edge; the option implementation adds no value after costs."))
        return StrategyClassification.INHERITED_FROM_UNDERLYING, "Apparent profitability is explained by the underlying's own move, not the options implementation.", tuple(criteria)
    criteria.append(GateCriterionResult(2, "not_explained_by_underlying", evidence.option_adds_value_after_costs, "See underlying-vs-option comparison."))

    if evidence.mean_net_pnl is not None and evidence.mean_net_pnl <= 0:
        criteria.append(GateCriterionResult(3, "positive_expectancy", False, f"mean_net_pnl=${evidence.mean_net_pnl:.2f}"))
        return StrategyClassification.REJECTED, f"Mean net P&L per trade is not positive (${evidence.mean_net_pnl:.2f}).", tuple(criteria)
    criteria.append(GateCriterionResult(3, "positive_expectancy", True, f"mean_net_pnl=${evidence.mean_net_pnl:.2f}" if evidence.mean_net_pnl is not None else "n/a"))

    bootstrap_ok = bool(evidence.bootstrap_excludes_zero_90pct)
    criteria.append(GateCriterionResult(4, "bootstrap_excludes_zero", evidence.bootstrap_excludes_zero_90pct, "90% bootstrap CI on mean trade P&L excludes zero."))

    cost_1x_ok = bool(evidence.cost_survives_1x)
    criteria.append(GateCriterionResult(5, "survives_1x_cost", evidence.cost_survives_1x, "Net P&L positive at 1x cost/slippage."))
    if not cost_1x_ok:
        return StrategyClassification.REJECTED, "Does not survive even baseline (1x) cost/slippage assumptions.", tuple(criteria)

    outlier_ok = evidence.outlier_dependent is False
    criteria.append(GateCriterionResult(6, "not_outlier_dependent", outlier_ok, "Top-1% of trades explain <= 50% of total positive P&L." if outlier_ok else "Top-1% of trades explain > 50% of total positive P&L."))

    loo_symbol_ok = bool(evidence.leave_one_symbol_out_all_positive)
    loo_period_ok = bool(evidence.leave_one_period_out_all_positive)
    criteria.append(GateCriterionResult(7, "survives_leave_one_symbol_out", evidence.leave_one_symbol_out_all_positive, "Excluding any single underlying never flips mean P&L negative."))
    criteria.append(GateCriterionResult(8, "survives_leave_one_period_out", evidence.leave_one_period_out_all_positive, "Excluding any single year never flips mean P&L negative."))

    placebo_ok = evidence.placebo_empirical_p is not None and evidence.placebo_empirical_p < 0.10
    criteria.append(GateCriterionResult(9, "placebo_separation", placebo_ok, f"empirical p={evidence.placebo_empirical_p}"))

    cost_2x_ok = bool(evidence.cost_survives_2x)
    cost_3x_ok = bool(evidence.cost_survives_3x)
    cost_5x_ok = bool(evidence.cost_survives_5x)
    criteria.append(GateCriterionResult(10, "survives_2x_3x_cost", cost_2x_ok and cost_3x_ok, "Net P&L positive at both 2x and 3x cost/slippage."))
    criteria.append(GateCriterionResult(11, "survives_5x_cost", cost_5x_ok, "Net P&L positive at 5x cost/slippage."))

    affordable_ok = evidence.pct_trades_affordable_1000usd is not None and evidence.pct_trades_affordable_1000usd >= 0.5
    criteria.append(GateCriterionResult(12, "affordable_for_1000usd_account", affordable_ok, f"pct_affordable={evidence.pct_trades_affordable_1000usd}"))

    fragile_reasons = []
    if not outlier_ok:
        fragile_reasons.append("outlier-dependent")
    if not (loo_symbol_ok and loo_period_ok):
        fragile_reasons.append("fails leave-one-out")
    if not (cost_2x_ok and cost_3x_ok):
        fragile_reasons.append("fails 2x/3x cost stress")
    if not placebo_ok:
        fragile_reasons.append("fails placebo separation")
    if not affordable_ok:
        fragile_reasons.append("not affordable for a $1,000 account")

    if fragile_reasons:
        return (
            StrategyClassification.TRADEABLE_SIGNAL_FRAGILE,
            f"Positive at baseline cost but fragile: {', '.join(fragile_reasons)}.",
            tuple(criteria),
        )

    if bootstrap_ok and cost_5x_ok:
        return StrategyClassification.VALIDATED_CANDIDATE, "Survives every criterion above, including 5x cost stress and a 90% bootstrap CI excluding zero.", tuple(criteria)

    if bootstrap_ok:
        return StrategyClassification.PROMISING, "Survives every criterion through 3x cost stress with a 90% bootstrap CI excluding zero, but not yet 5x.", tuple(criteria)

    return StrategyClassification.INCONCLUSIVE, "Survives cost/outlier/leave-one-out/placebo/affordability checks, but the bootstrap CI does not exclude zero -- not decisive either way.", tuple(criteria)
