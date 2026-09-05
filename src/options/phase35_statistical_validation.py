"""Phase 35, Parts I-K/T — year-by-year/symbol-by-symbol robustness,
falsification (placebo/outlier/leave-one-out), and the underlying-vs-
option control. Operates entirely on the REAL trade list produced by
`phase35_backtest_campaign.run_baseline_backtest` -- reuses
`src.research.placebo.bootstrap_trade_statistics`/
`block_bootstrap_trade_statistics` unchanged for confidence intervals.

No parameter of `MOMENTUM_BREAKOUT_EXISTING_V1` is ever altered here
(Phase 35's explicit prohibition) -- every function below either
partitions/perturbs the REAL, ALREADY-COMPUTED trade list, or re-runs the
UNCHANGED strategy/matching pipeline against randomized dates (a
placebo), never a re-optimized or re-tuned rule.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Sequence

from src.backtesting.journal import BacktestTrade
from src.options.phase35_option_trade_matching import MatchedOptionTrade, find_matching_contract_trade
from src.options.phase35_underlying_signal import UnderlyingSignalEvent
from src.research.placebo import BootstrapReport, bootstrap_trade_statistics


@dataclass(frozen=True)
class SimpleTradeStats:
    n_trades: int
    win_rate: float | None
    total_net_pnl: float
    mean_net_pnl: float | None
    median_net_pnl: float | None
    expectancy: float | None  # same as mean_net_pnl -- named per Part E's own vocabulary
    profit_factor: float | None


def simple_trade_stats(trades: Sequence[BacktestTrade]) -> SimpleTradeStats:
    pnls = [t.net_pnl for t in trades]
    n = len(pnls)
    if n == 0:
        return SimpleTradeStats(0, None, 0.0, None, None, None, None)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else None)
    return SimpleTradeStats(
        n_trades=n, win_rate=len(wins) / n, total_net_pnl=sum(pnls), mean_net_pnl=statistics.mean(pnls),
        median_net_pnl=statistics.median(pnls), expectancy=statistics.mean(pnls), profit_factor=profit_factor,
    )


def symbol_of(trade: BacktestTrade, matched_by_option_id: dict[str, MatchedOptionTrade]) -> str:
    m = matched_by_option_id.get(trade.symbol)
    return m.underlying_symbol if m is not None else trade.symbol


def year_by_year_breakdown(trades: Sequence[BacktestTrade]) -> dict[int, SimpleTradeStats]:
    by_year: dict[int, list[BacktestTrade]] = {}
    for t in trades:
        by_year.setdefault(t.entry_timestamp.year, []).append(t)
    return {y: simple_trade_stats(ts) for y, ts in sorted(by_year.items())}


def symbol_by_symbol_breakdown(trades: Sequence[BacktestTrade], matched_trades: Sequence[MatchedOptionTrade]) -> dict[str, SimpleTradeStats]:
    matched_by_id = {m.option_id: m for m in matched_trades}
    by_symbol: dict[str, list[BacktestTrade]] = {}
    for t in trades:
        by_symbol.setdefault(symbol_of(t, matched_by_id), []).append(t)
    return {s: simple_trade_stats(ts) for s, ts in sorted(by_symbol.items())}


def leave_one_symbol_out(trades: Sequence[BacktestTrade], matched_trades: Sequence[MatchedOptionTrade]) -> dict[str, SimpleTradeStats]:
    matched_by_id = {m.option_id: m for m in matched_trades}
    symbols = sorted({symbol_of(t, matched_by_id) for t in trades})
    return {
        s: simple_trade_stats([t for t in trades if symbol_of(t, matched_by_id) != s])
        for s in symbols
    }


def leave_one_period_out(trades: Sequence[BacktestTrade]) -> dict[int, SimpleTradeStats]:
    years = sorted({t.entry_timestamp.year for t in trades})
    return {y: simple_trade_stats([t for t in trades if t.entry_timestamp.year != y]) for y in years}


@dataclass(frozen=True)
class OutlierAnalysis:
    top1pct_contribution_fraction: float | None  # top ceil(1%) trades' share of TOTAL POSITIVE pnl sum
    stats_excluding_largest_winner: SimpleTradeStats
    stats_excluding_top_1pct: SimpleTradeStats


def outlier_analysis(trades: Sequence[BacktestTrade]) -> OutlierAnalysis:
    pnls = [t.net_pnl for t in trades]
    n = len(trades)
    if n == 0:
        empty = simple_trade_stats([])
        return OutlierAnalysis(None, empty, empty)
    sorted_trades = sorted(trades, key=lambda t: t.net_pnl, reverse=True)
    positive_sum = sum(p for p in pnls if p > 0)
    n_top = max(1, round(n * 0.01))
    top = sorted_trades[:n_top]
    top1pct_sum = sum(t.net_pnl for t in top)
    fraction = (top1pct_sum / positive_sum) if positive_sum > 0 else None
    return OutlierAnalysis(
        top1pct_contribution_fraction=fraction,
        stats_excluding_largest_winner=simple_trade_stats(sorted_trades[1:]),
        stats_excluding_top_1pct=simple_trade_stats(sorted_trades[n_top:]),
    )


@dataclass(frozen=True)
class PlaceboResult:
    method: str
    n_trials: int
    observed_statistic: float
    empirical_p_value: float | None  # fraction of placebo trials with a statistic >= observed
    n_real_placebo_matches_per_trial: list[int]


def random_entry_date_placebo(
    *, observed_trades: Sequence[BacktestTrade], signals_by_underlying: dict[str, tuple[UnderlyingSignalEvent, ...]],
    underlying_daily_series: dict[str, list[tuple[date, float]]], contract_day_rows: list[dict],
    statistic_fn=lambda pnls: (statistics.mean(pnls) if pnls else 0.0), n_trials: int = 50, seed: int = 42,
) -> PlaceboResult:
    """Part J's shuffled-signal / feature-shuffle placebo, adapted to this
    trade-list's shape: for each underlying, draws the SAME NUMBER of
    RANDOM real trading dates (seeded, reproducible) as the strategy
    actually fired signals on, matches them to REAL option contracts via
    the SAME UNCHANGED `find_matching_contract_trade`, and compares the
    resulting real trade list's statistic to the observed one -- the
    ONLY thing randomized is WHICH dates count as a signal; the matching
    and pricing pipeline is identical and never altered."""
    observed_stat = statistic_fn([t.net_pnl for t in observed_trades])
    rng = random.Random(seed)
    simulated: list[float] = []
    match_counts: list[int] = []

    for trial in range(n_trials):
        trial_pnls: list[float] = []
        n_matched_this_trial = 0
        for underlying, real_signals in signals_by_underlying.items():
            series = underlying_daily_series.get(underlying, [])
            if not series or not real_signals:
                continue
            n_needed = len(real_signals)
            candidate_dates = [d for d, _ in series]
            chosen_dates = rng.sample(candidate_dates, min(n_needed, len(candidate_dates)))
            price_by_date = dict(series)
            for d in chosen_dates:
                fake_signal = UnderlyingSignalEvent(underlying_symbol=underlying, signal_date=d, underlying_price=price_by_date[d], signals_fired=())
                m = find_matching_contract_trade(fake_signal, contract_day_rows)
                if m is None or len(m.management_rows) < 1:
                    continue
                n_matched_this_trial += 1
                entry = m.entry_row
                exit_row = m.management_rows[-1]
                entry_price = entry.get("ask") or entry.get("bid")
                exit_price = ((exit_row.get("bid") or 0) + (exit_row.get("ask") or 0)) / 2 or exit_row.get("ask") or exit_row.get("bid")
                if entry_price and exit_price:
                    trial_pnls.append((exit_price - entry_price) * 100)
        simulated.append(statistic_fn(trial_pnls))
        match_counts.append(n_matched_this_trial)

    p = (sum(1 for s in simulated if s >= observed_stat) / len(simulated)) if simulated else None
    return PlaceboResult(
        method="random_entry_date_placebo: same per-underlying signal COUNT, real dates drawn uniformly at random (seeded), "
               "same real contract-matching pipeline, unchanged",
        n_trials=n_trials, observed_statistic=observed_stat, empirical_p_value=p, n_real_placebo_matches_per_trial=match_counts,
    )


@dataclass(frozen=True)
class UnderlyingVsOptionRow:
    option_id: str
    underlying_symbol: str
    underlying_return_pct: float | None  # entry-date-close to exit-date-close, real underlying prices
    option_return_pct: float | None
    option_net_pnl_usd: float


def underlying_vs_option_rows(
    trades: Sequence[BacktestTrade], matched_trades: Sequence[MatchedOptionTrade], underlying_daily_series: dict[str, list[tuple[date, float]]],
) -> list[UnderlyingVsOptionRow]:
    """Part K: for each REAL matched trade, the underlying's OWN simple
    return over the SAME entry->exit window, alongside the option
    trade's own return -- never substituting one for the other, only
    placed side by side for comparison."""
    matched_by_id = {m.option_id: m for m in matched_trades}
    rows = []
    for t in trades:
        m = matched_by_id.get(t.symbol)
        if m is None:
            continue
        series = dict(underlying_daily_series.get(m.underlying_symbol, []))
        entry_u = series.get(t.entry_timestamp.date())
        exit_u = series.get(t.exit_timestamp.date())
        underlying_return = (exit_u - entry_u) / entry_u if (entry_u and exit_u and entry_u != 0) else None
        option_return = (t.exit_price - t.entry_price) / t.entry_price if t.entry_price else None
        rows.append(UnderlyingVsOptionRow(
            option_id=t.symbol, underlying_symbol=m.underlying_symbol, underlying_return_pct=underlying_return,
            option_return_pct=option_return, option_net_pnl_usd=t.net_pnl,
        ))
    return rows


def bootstrap(trades: Sequence[BacktestTrade]) -> BootstrapReport:
    return bootstrap_trade_statistics(list(trades))
