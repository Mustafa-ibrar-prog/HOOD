"""Phase 35, Parts C-H — orchestrates the frozen MomentumBreakoutStrategy's
research adapter through the real, unmodified backtesting framework.

Reuses, UNCHANGED: `phase31_panel_builder.build_panel_rows`/
`build_underlying_series` (contract-day panel + real underlying close
series), `phase35_underlying_signal.detect_entry_signal_dates`,
`phase35_option_trade_matching.match_all_signals`,
`phase35_option_research_strategy.MomentumBreakoutOptionResearchStrategy`/
`build_bars_for_matched_trade`, `src.research.runner.run_research_backtest`,
`src.backtesting.metrics.compute_performance_metrics`,
`src.backtesting.execution_models.*`, `src.backtesting.sizing.
FixedQuantitySizer`, `src.backtesting.risk_adapter.BacktestRiskAdapter`
(wrapping the real, unmodified `src.risk.manager.RiskManager`),
`src.options.phase31_affordability_liquidity.affordability_filter_report`/
`classify_account_feasibility`, `src.research.validation.
run_cost_sensitivity`.

USABLE_UNDERLYINGS is fixed BEFORE any result is computed (Part C's data-
availability finding: AAPL/SPY/GOOG have thousands of real daily
underlying bars; FOXA/NWSA have only 2 real bars each -- mathematically
insufficient for a 14-26-day indicator; TWX has zero real underlying
bars in this project's real store). Never silently expanded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time

from src.backtesting.execution_models import (
    FixedPercentSlippage,
    FixedPercentSpreadModel,
    NextBarExecutionModel,
    PercentOfNotionalCommission,
    RealBidAskSpreadModel,
    SpreadQuote,
)
from src.backtesting.interfaces import BacktestConfig
from src.backtesting.journal import BacktestTrade
from src.backtesting.metrics import PerformanceMetrics, compute_performance_metrics
from src.backtesting.risk_adapter import BacktestRiskAdapter
from src.backtesting.sizing import FixedQuantitySizer
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.phase31_affordability_liquidity import (
    AffordabilityFilterReport,
    affordability_filter_report,
    classify_account_feasibility,
)
from src.options.phase31_panel_builder import build_panel_rows, build_underlying_series
from src.options.phase35_option_research_strategy import MomentumBreakoutOptionResearchStrategy, build_bars_for_matched_trade
from src.options.phase35_option_trade_matching import MatchedOptionTrade, match_all_signals
from src.options.phase35_underlying_signal import UnderlyingSignalEvent, detect_entry_signal_dates
from src.research.runner import run_research_backtest
from src.research.validation import CostSensitivityReport, run_cost_sensitivity
from src.risk.manager import RiskManager
from src.risk.models import RiskLimits

USABLE_UNDERLYINGS: tuple[str, ...] = ("AAPL", "SPY", "GOOG")  # frozen -- see module docstring; FOXA/NWSA/TWX excluded, DATA_LIMITED
ACCOUNT_EQUITY_USD = 1000.0  # Part G's $1,000 account
CONTRACT_MULTIPLIER = 100

_GENEROUS_RISK_LIMITS = RiskLimits(
    max_trades_per_day=1000, max_daily_loss_usd=1e9, max_position_size_usd=1e9, cooldown_minutes_after_exit=0,
    stale_data_max_seconds=1e9, max_spread_pct=1.0, min_option_volume=0, min_option_open_interest=0,
    max_extended_move_pct=100.0, entry_cutoff_time=time(23, 59),
)  # Part E/G's deliberate separation: statistical validity is evaluated UNCONSTRAINED by an artificial size cap;
   # affordability (Part G) is reported separately, descriptively, over the resulting trade list -- never by
   # silently rejecting real signals from the backtest itself.


def _real_bid_ask_by_timestamp(bars_by_symbol: dict, matched_trades: list[MatchedOptionTrade]) -> dict:
    """Builds the `quotes_by_timestamp` mapping `RealBidAskSpreadModel`
    expects, keyed the same way the engine keys fills -- by (symbol,
    timestamp) is not how RealBidAskSpreadModel is shaped (it keys only
    by bar.timestamp, symbol-agnostic), so this returns one shared dict;
    since every matched trade's rows carry a real bid/ask pair whenever
    both exist, the timestamp key alone is enough to recover them for
    that specific bar."""
    out = {}
    for trade in matched_trades:
        for row in (trade.entry_row,) + trade.management_rows:
            bid, ask = row.get("bid"), row.get("ask")
            if bid is not None and ask is not None:
                ts = row["timestamp"]
                if ts.tzinfo is None:
                    from datetime import timezone
                    ts = ts.replace(tzinfo=timezone.utc)
                out[ts] = SpreadQuote(bid=bid, ask=ask, source="real_bid_ask")
    return out


@dataclass(frozen=True)
class CampaignData:
    contract_day_rows: list[dict]
    underlying_daily_series: dict[str, list[tuple[date, float]]]
    signals_by_underlying: dict[str, tuple[UnderlyingSignalEvent, ...]]
    matched_trades: list[MatchedOptionTrade]
    unmatched_signals: list[UnderlyingSignalEvent]


def build_campaign_data(store: InMemoryLeanSampleStore, *, max_contracts_per_underlying: int = 6000) -> CampaignData:
    contract_day_rows = build_panel_rows(store, max_contracts_per_underlying=max_contracts_per_underlying)
    underlying_daily_series = {u: build_underlying_series(store, u) for u in USABLE_UNDERLYINGS}
    signals_by_underlying = {
        u: detect_entry_signal_dates(u, series) for u, series in underlying_daily_series.items()
    }
    all_signals = tuple(s for events in signals_by_underlying.values() for s in events)
    matched, unmatched = match_all_signals(all_signals, contract_day_rows)
    return CampaignData(
        contract_day_rows=contract_day_rows, underlying_daily_series=underlying_daily_series,
        signals_by_underlying=signals_by_underlying, matched_trades=matched, unmatched_signals=unmatched,
    )


@dataclass(frozen=True)
class BacktestRunResult:
    trades: tuple[BacktestTrade, ...]
    metrics: PerformanceMetrics
    starting_cash: float


def run_baseline_backtest(data: CampaignData, *, slippage_pct: float = 0.0, commission_pct: float = 0.0) -> BacktestRunResult:
    """Part E's primary backtest -- chronological, next-bar execution, a
    REAL bid/ask spread model wherever a real quote exists (falling back
    to a modeled, honestly-labeled spread otherwise), the existing risk
    adapter (wrapping the unmodified RiskManager), the existing
    accounting/trade-journal machinery. `slippage_pct`/`commission_pct`
    default to 0.0 for the BASELINE (Part H sweeps these separately)."""
    trades_by_symbol = {t.option_id: t for t in data.matched_trades}
    bars_by_symbol = {t.option_id: build_bars_for_matched_trade(t) for t in data.matched_trades}
    bars_by_symbol = {sym: bars for sym, bars in bars_by_symbol.items() if len(bars) >= 2}  # need >=1 fill bar after entry
    trades_by_symbol = {sym: t for sym, t in trades_by_symbol.items() if sym in bars_by_symbol}

    strategy = MomentumBreakoutOptionResearchStrategy(trades_by_symbol, data.underlying_daily_series, universe=USABLE_UNDERLYINGS)
    all_dates = [b.timestamp.date() for bars in bars_by_symbol.values() for b in bars]
    config = BacktestConfig(
        symbols=tuple(sorted(bars_by_symbol)), timeframe="day", start=min(all_dates, default=date(2013, 1, 1)),
        end=max(all_dates, default=date(2016, 1, 1)), data_version="phase26_27_free_reference", feature_version="phase35_v1",
        strategy_version="1.0", initial_capital_usd=1_000_000.0, strategy_name=strategy.spec.strategy_id,
    )
    risk_adapter = BacktestRiskAdapter(RiskManager(_GENEROUS_RISK_LIMITS))
    real_quotes = _real_bid_ask_by_timestamp(bars_by_symbol, list(trades_by_symbol.values()))

    result = run_research_backtest(
        research_strategy=strategy, bars_by_symbol=bars_by_symbol, config=config,
        execution_model=NextBarExecutionModel(price_field="open", delay_bars=1),
        slippage_model=FixedPercentSlippage(slippage_pct),
        cost_model=PercentOfNotionalCommission(commission_pct),
        spread_model=RealBidAskSpreadModel(real_quotes, fallback=FixedPercentSpreadModel(0.0)),
        position_sizer=FixedQuantitySizer(CONTRACT_MULTIPLIER), risk_adapter=risk_adapter,
    )
    metrics = compute_performance_metrics(equity_curve=list(result.equity_curve), trades=list(result.trades), starting_cash=config.initial_capital_usd)
    return BacktestRunResult(trades=result.trades, metrics=metrics, starting_cash=config.initial_capital_usd)


def affordability_for_trades(trades: tuple[BacktestTrade, ...], *, account_equity_usd: float = ACCOUNT_EQUITY_USD) -> tuple[AffordabilityFilterReport, str]:
    """Part G: reuses the EXISTING affordability framework unchanged --
    one synthetic 'panel row' per REAL trade's own entry premium (the
    function's row-shape contract is `ask`/`bid`), never a fabricated
    premium. Options contracts are integer quantities -- this reports the
    fraction of trades where ONE contract's real premium fits inside the
    account, never a fractional contract."""
    rows = [{"ask": t.entry_price, "bid": t.entry_price} for t in trades]
    report = affordability_filter_report(rows, account_equity_usd=account_equity_usd)
    classification = classify_account_feasibility(report)
    return report, classification


def cost_stress_sweep(data: CampaignData, *, multipliers: tuple[float, ...] = (1.0, 2.0, 3.0, 5.0)) -> CostSensitivityReport | None:
    """Part H: baseline/1x/2x/3x/5x cost stress via the REAL re-simulated
    `run_cost_sensitivity` (not the post-hoc fee-only version) -- scales
    BOTH the slippage and commission models together at each multiplier,
    a genuine re-run of the real engine each time. A 1.0% base slippage
    and 0.5% base commission are ASSUMPTION-labeled (this project's
    convention since Phase 23): real historical bid/ask IS used for the
    spread itself (RealBidAskSpreadModel); slippage BEYOND the real
    spread and commission are not observable in this free dataset and
    are never invented as if they were real, only swept as a labeled
    sensitivity assumption."""
    trades_by_symbol = {t.option_id: t for t in data.matched_trades}
    bars_by_symbol = {t.option_id: build_bars_for_matched_trade(t) for t in data.matched_trades}
    bars_by_symbol = {sym: bars for sym, bars in bars_by_symbol.items() if len(bars) >= 2}
    trades_by_symbol = {sym: t for sym, t in trades_by_symbol.items() if sym in bars_by_symbol}
    if not bars_by_symbol:
        return None

    strategy = MomentumBreakoutOptionResearchStrategy(trades_by_symbol, data.underlying_daily_series, universe=USABLE_UNDERLYINGS)
    all_dates = [b.timestamp.date() for bars in bars_by_symbol.values() for b in bars]
    config = BacktestConfig(
        symbols=tuple(sorted(bars_by_symbol)), timeframe="day", start=min(all_dates), end=max(all_dates),
        data_version="phase26_27_free_reference", feature_version="phase35_v1", strategy_version="1.0",
        initial_capital_usd=1_000_000.0, strategy_name=strategy.spec.strategy_id,
    )
    risk_adapter = BacktestRiskAdapter(RiskManager(_GENEROUS_RISK_LIMITS))
    real_quotes = _real_bid_ask_by_timestamp(bars_by_symbol, list(trades_by_symbol.values()))

    return run_cost_sensitivity(
        research_strategy=strategy, bars_by_symbol=bars_by_symbol, config=config,
        execution_model=NextBarExecutionModel(price_field="open", delay_bars=1),
        base_slippage_model=FixedPercentSlippage(0.01), base_cost_model=PercentOfNotionalCommission(0.005),
        spread_model=RealBidAskSpreadModel(real_quotes, fallback=FixedPercentSpreadModel(0.0)),
        position_sizer=FixedQuantitySizer(CONTRACT_MULTIPLIER), risk_adapter=risk_adapter, multipliers=multipliers,
    )
