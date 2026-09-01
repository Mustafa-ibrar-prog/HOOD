"""Phase 6, section 18: objective pass/fail criteria for the holdout,
defined and written to disk BEFORE the holdout is run — see
scripts/phase6_define_pass_criteria.py, which must execute (and commit its
output file) strictly before scripts/phase6_run_holdout.py touches any
holdout data. These are research gates, not a promise of profitability:
clearing every one of them means the frozen strategy's characteristics
held up under a genuinely unseen test, not that it will make money going
forward.

`PreRegisteredAt` on `HoldoutPassCriteria` records when the criteria were
fixed; `evaluate_pass_criteria` is a pure function of
(criteria, holdout evidence) — it does not know about, and cannot be
tuned by, the eventual number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True)
class HoldoutPassCriteria:
    """Every threshold here was picked using ONLY Phase 4/5 conventions
    already established before Phase 6's holdout was run (e.g.
    MIN_OOS_TRADES_FOR_A_VERDICT=20 from src.research.classification,
    "viable" == net_pnl_total > 0 from src.research.validation) — none of
    it was reverse-engineered from a holdout number, because at the time
    this dataclass was written and saved to disk, no holdout backtest had
    been executed."""

    min_holdout_trade_count: int = 20  # matches classification.MIN_OOS_TRADES_FOR_A_VERDICT
    require_positive_expectancy: bool = True
    require_positive_net_pnl: bool = True
    max_acceptable_drawdown_pct: float = 35.0  # a holdout drawdown worse than this is disqualifying regardless of the final return
    min_acceptable_profit_factor: float = 1.0  # profit_factor >= 1.0 means gross profit >= gross loss
    max_single_symbol_pnl_share_pct: float = 60.0  # no single symbol may explain more than this fraction of total net P&L
    max_top_5pct_trades_pnl_share_pct: float = 60.0  # no 5% sliver of trades may explain more than this fraction
    require_viable_at_2x_costs: bool = True
    require_viable_under_extra_execution_delay: bool = True
    max_single_year_pnl_share_pct: float = 75.0  # no single calendar year may explain more than this fraction (dominance-by-one-period check)
    pre_registered_at: datetime | None = None
    notes: str = (
        "Defined before scripts/phase6_run_holdout.py was ever executed. Thresholds reuse this codebase's existing "
        "conventions (MIN_OOS_TRADES_FOR_A_VERDICT, viable == net_pnl_total > 0) rather than new numbers invented "
        "for this phase, to avoid the appearance (or reality) of picking numbers that flatter a specific result."
    )

    def as_dict(self) -> dict:
        d = {
            "min_holdout_trade_count": self.min_holdout_trade_count,
            "require_positive_expectancy": self.require_positive_expectancy,
            "require_positive_net_pnl": self.require_positive_net_pnl,
            "max_acceptable_drawdown_pct": self.max_acceptable_drawdown_pct,
            "min_acceptable_profit_factor": self.min_acceptable_profit_factor,
            "max_single_symbol_pnl_share_pct": self.max_single_symbol_pnl_share_pct,
            "max_top_5pct_trades_pnl_share_pct": self.max_top_5pct_trades_pnl_share_pct,
            "require_viable_at_2x_costs": self.require_viable_at_2x_costs,
            "require_viable_under_extra_execution_delay": self.require_viable_under_extra_execution_delay,
            "max_single_year_pnl_share_pct": self.max_single_year_pnl_share_pct,
            "pre_registered_at": self.pre_registered_at.isoformat() if self.pre_registered_at else None,
            "notes": self.notes,
        }
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HoldoutPassCriteria":
        data = dict(data)
        pre_registered_at = data.get("pre_registered_at")
        return cls(
            min_holdout_trade_count=data.get("min_holdout_trade_count", 20),
            require_positive_expectancy=data.get("require_positive_expectancy", True),
            require_positive_net_pnl=data.get("require_positive_net_pnl", True),
            max_acceptable_drawdown_pct=data.get("max_acceptable_drawdown_pct", 35.0),
            min_acceptable_profit_factor=data.get("min_acceptable_profit_factor", 1.0),
            max_single_symbol_pnl_share_pct=data.get("max_single_symbol_pnl_share_pct", 60.0),
            max_top_5pct_trades_pnl_share_pct=data.get("max_top_5pct_trades_pnl_share_pct", 60.0),
            require_viable_at_2x_costs=data.get("require_viable_at_2x_costs", True),
            require_viable_under_extra_execution_delay=data.get("require_viable_under_extra_execution_delay", True),
            max_single_year_pnl_share_pct=data.get("max_single_year_pnl_share_pct", 75.0),
            pre_registered_at=datetime.fromisoformat(pre_registered_at) if pre_registered_at else None,
            notes=data.get("notes", ""),
        )


@dataclass(frozen=True)
class PassCriterionResult:
    name: str
    passed: bool | None  # None = could not be evaluated (e.g. metric unavailable)
    detail: str


@dataclass(frozen=True)
class PassCriteriaEvaluation:
    results: tuple[PassCriterionResult, ...]

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results if r.passed is not None) and all(r.passed is not None for r in self.results)

    @property
    def fraction_passed(self) -> float:
        evaluated = [r for r in self.results if r.passed is not None]
        if not evaluated:
            return 0.0
        return sum(1 for r in evaluated if r.passed) / len(evaluated)

    def render(self) -> str:
        lines = ["HOLDOUT PASS-CRITERIA EVALUATION (pre-registered before the holdout was run)", ""]
        for r in self.results:
            status = "PASS" if r.passed is True else "FAIL" if r.passed is False else "N/A"
            lines.append(f"  [{status}] {r.name}: {r.detail}")
        lines.append("")
        lines.append(f"Overall: {sum(1 for r in self.results if r.passed is True)}/{len(self.results)} criteria passed (all_passed={self.all_passed})")
        return "\n".join(lines)


def evaluate_pass_criteria(
    criteria: HoldoutPassCriteria,
    *,
    trade_count: int,
    expectancy: float,
    net_pnl_total: float,
    max_drawdown_pct: float | None,
    profit_factor: float | None,
    max_symbol_pnl_share_pct: float | None,
    top_5pct_trades_pnl_share_pct: float | None,
    viable_at_2x_costs: bool | None,
    viable_under_extra_execution_delay: bool | None,
    max_year_pnl_share_pct: float | None,
) -> PassCriteriaEvaluation:
    """A pure function: (criteria, evidence) -> evaluation. Never reads
    from or writes to any file — it cannot see anything except what its
    caller explicitly passes in."""
    results = [
        PassCriterionResult("minimum trade count", trade_count >= criteria.min_holdout_trade_count, f"{trade_count} trades (required >= {criteria.min_holdout_trade_count})"),
        PassCriterionResult("positive expectancy", (expectancy > 0) if criteria.require_positive_expectancy else None, f"expectancy=${expectancy:.2f}/trade"),
        PassCriterionResult("positive net P&L", (net_pnl_total > 0) if criteria.require_positive_net_pnl else None, f"net_pnl_total=${net_pnl_total:.2f}"),
        PassCriterionResult(
            "acceptable max drawdown",
            (abs(max_drawdown_pct) <= criteria.max_acceptable_drawdown_pct) if max_drawdown_pct is not None else None,
            f"max_drawdown={max_drawdown_pct}% (required <= {criteria.max_acceptable_drawdown_pct}%)" if max_drawdown_pct is not None else "unavailable",
        ),
        PassCriterionResult(
            "acceptable profit factor",
            (profit_factor >= criteria.min_acceptable_profit_factor) if profit_factor is not None else None,
            f"profit_factor={profit_factor} (required >= {criteria.min_acceptable_profit_factor})" if profit_factor is not None else "unavailable (no losing trades or no trades)",
        ),
        PassCriterionResult(
            "no single-symbol dominance",
            (max_symbol_pnl_share_pct <= criteria.max_single_symbol_pnl_share_pct) if max_symbol_pnl_share_pct is not None else None,
            f"largest symbol share={max_symbol_pnl_share_pct:.1f}% (required <= {criteria.max_single_symbol_pnl_share_pct}%)" if max_symbol_pnl_share_pct is not None else "unavailable",
        ),
        PassCriterionResult(
            "no top-5%-of-trades dominance",
            (top_5pct_trades_pnl_share_pct <= criteria.max_top_5pct_trades_pnl_share_pct) if top_5pct_trades_pnl_share_pct is not None else None,
            f"top 5% of trades = {top_5pct_trades_pnl_share_pct:.1f}% of P&L (required <= {criteria.max_top_5pct_trades_pnl_share_pct}%)" if top_5pct_trades_pnl_share_pct is not None else "unavailable",
        ),
        PassCriterionResult("survives 2x transaction costs", viable_at_2x_costs if criteria.require_viable_at_2x_costs else None, f"viable_at_2x_costs={viable_at_2x_costs}"),
        PassCriterionResult("survives extra execution delay", viable_under_extra_execution_delay if criteria.require_viable_under_extra_execution_delay else None, f"viable_under_extra_execution_delay={viable_under_extra_execution_delay}"),
        PassCriterionResult(
            "no single-year dominance",
            (max_year_pnl_share_pct <= criteria.max_single_year_pnl_share_pct) if max_year_pnl_share_pct is not None else None,
            f"largest year share={max_year_pnl_share_pct:.1f}% (required <= {criteria.max_single_year_pnl_share_pct}%)" if max_year_pnl_share_pct is not None else "unavailable",
        ),
    ]
    return PassCriteriaEvaluation(results=tuple(results))
