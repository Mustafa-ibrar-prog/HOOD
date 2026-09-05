"""Phase 38, Part 10 — economic validation beyond bare statistical
significance.

Reuses `src.research.stats_utils.sharpe_ratio_from_returns` (already
established, 0% risk-free rate, same convention as
`src.backtesting.metrics`) rather than a new ratio implementation.
Sortino/drawdown/payoff-ratio are new here only because no existing
module in this project computes them over a bare RETURN SEQUENCE (as
opposed to `src.backtesting.metrics`'s `EquityPoint` curve, which this
phase's live-observation-derived trades don't produce -- see
`phase38_targets.py`'s module docstring).

Aggressive is not conflated with reckless (Part 10's explicit
instruction): this module reports the real numbers -- including
drawdown and ruin-relevant tail statistics -- without imposing an
arbitrary "safe" cutoff of its own. Whether a number is acceptable is
the validation gate's job (`phase38_validation_gate.py`), not this
module's.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Sequence

from src.options.phase38_targets import ForwardOutcome
from src.research.stats_utils import sharpe_ratio_from_returns


@dataclass(frozen=True)
class EconomicValidationReport:
    n_trades: int
    expectancy: float | None  # mean executable return
    median_return: float | None
    mean_return: float | None
    win_rate: float | None
    payoff_ratio: float | None  # average win / average |loss|
    profit_factor: float | None  # gross win / gross |loss|
    max_drawdown_pct: float | None  # over the SEQUENCE of trade returns, compounded in trade order
    volatility: float | None  # stdev of per-trade returns
    sharpe_like: float | None  # per-TRADE Sharpe (not annualized -- there is no fixed trading-day cadence for irregularly-timed live observations)
    sortino_like: float | None  # same, using only downside deviation
    turnover_trades_per_day: float | None
    average_holding_period_minutes: float | None


def _max_drawdown_pct(returns: Sequence[float]) -> float | None:
    if not returns:
        return None
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        equity *= (1 + r)
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
    return max_dd


def _sortino_like(returns: Sequence[float]) -> float | None:
    if len(returns) < 2:
        return None
    downside = [r for r in returns if r < 0]
    if not downside:
        return None
    downside_dev = statistics.pstdev(downside)
    if downside_dev == 0:
        return None
    return statistics.mean(returns) / downside_dev


def build_economic_validation_report(outcomes: Sequence[ForwardOutcome]) -> EconomicValidationReport:
    ordered = sorted(outcomes, key=lambda o: o.entry_timestamp)
    returns = [o.executable_return_pct for o in ordered if o.executable_return_pct is not None]
    n = len(returns)
    if n == 0:
        return EconomicValidationReport(0, None, None, None, None, None, None, None, None, None, None, None, None)

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    avg_win = statistics.mean(wins) if wins else None
    avg_loss = statistics.mean(losses) if losses else None
    payoff_ratio = (avg_win / abs(avg_loss)) if avg_win is not None and avg_loss not in (None, 0) else None
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else None)

    holding_periods = [
        (o.exit_timestamp - o.entry_timestamp).total_seconds() / 60
        for o in ordered if o.exit_timestamp is not None
    ]
    days_spanned = max(1.0, (ordered[-1].entry_timestamp - ordered[0].entry_timestamp).total_seconds() / 86400) if n > 1 else 1.0

    return EconomicValidationReport(
        n_trades=n, expectancy=statistics.mean(returns), median_return=statistics.median(returns),
        mean_return=statistics.mean(returns), win_rate=len(wins) / n, payoff_ratio=payoff_ratio,
        profit_factor=profit_factor, max_drawdown_pct=_max_drawdown_pct(returns),
        volatility=statistics.pstdev(returns) if n >= 2 else None,
        sharpe_like=sharpe_ratio_from_returns(returns, periods_per_year=1.0) if n >= 2 else None,
        sortino_like=_sortino_like(returns), turnover_trades_per_day=n / days_spanned,
        average_holding_period_minutes=statistics.mean(holding_periods) if holding_periods else None,
    )
