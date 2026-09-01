#!/usr/bin/env python3
"""Phase 6 — STEP 5 (the main event): runs the FROZEN MR-002 definition,
exactly as frozen, against two complementary holdouts that were never
touched by any Phase 4/5 parameter/strategy selection:

  PRIMARY (temporal) holdout   — US_DIVERSIFIED, the exact dates
                                  2026-08-06..2026-08-31 that fall after
                                  every Phase 4/5 walk-forward window's
                                  test_end (computed in step 2). Small
                                  sample by construction — reported
                                  honestly, not padded.

  SECONDARY (universe) holdout — US_DIVERSIFIED_SECONDARY, its ENTIRE
                                  available history. None of these 20
                                  symbols were used in any Phase 4/5
                                  tuning at all, so the whole period
                                  counts as unseen for this strategy.

NO parameter sweep, NO walk-forward re-optimization, NO strategy
selection happens anywhere in this script — the strategy is instantiated
ONCE per universe from the FrozenStrategyStore record and never touched
again. Read-only historical data only — no orders of any kind.

This script is intended to run EXACTLY ONCE. Re-running it is safe
(idempotent business logic) but re-running it repeatedly "to see if the
number changes" would defeat the entire point of a holdout test — don't.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtesting import (  # noqa: E402
    BacktestConfig,
    BacktestRiskAdapter,
    FixedPercentSlippage,
    FixedPercentSpreadModel,
    FixedQuantitySizer,
    NextBarExecutionModel,
    PerShareCommission,
)
from src.backtesting.journal import BacktestTrade  # noqa: E402
from src.backtesting.metrics import compute_performance_metrics  # noqa: E402
from src.data import HistoricalDataStore, run_universe_quality_report, us_diversified_secondary_universe, us_diversified_universe  # noqa: E402
from src.risk.manager import RiskManager  # noqa: E402
from src.risk.models import RiskLimits  # noqa: E402
from src.research import (  # noqa: E402
    ExperimentStore,
    FrozenStrategyStore,
    HoldoutPassCriteria,
    bootstrap_trade_statistics,
    build_strategy_from_frozen,
    bucket_trades_by_regime,
    by_sector,
    by_symbol,
    by_year,
    classify_strategy,
    compute_search_space_summary,
    concentration_summary,
    determine_gate_stage,
    evaluate_pass_criteria,
    filter_bars_by_date,
    label_bars_by_regime,
    leave_one_symbol_out,
    random_symbol_and_timing_placebo,
    randomized_entry_timing_placebo,
    regime_performance_report,
    run_cost_sensitivity,
    run_execution_robustness_extended,
    run_research_backtest,
    trade_return_distribution,
)
from src.research.classification import MIN_OOS_TRADES_FOR_A_VERDICT
from src.research.validation import CostSensitivityPoint, CostSensitivityReport, ExecutionRobustnessPoint, ExecutionRobustnessReport, _ScaledCostModel, _ScaledSlippageModel

QUANTITY = 20
STARTING_CASH = 100_000.0


def _risk_adapter() -> BacktestRiskAdapter:
    limits = RiskLimits(max_trades_per_day=10, max_daily_loss_usd=1_000_000.0, max_position_size_usd=20_000.0, cooldown_minutes_after_exit=0, stale_data_max_seconds=10**9, max_spread_pct=1.0, min_option_volume=0, min_option_open_interest=0, max_extended_move_pct=100.0, entry_cutoff_time=__import__("datetime").time(23, 59))
    return BacktestRiskAdapter(RiskManager(limits))


def _models():
    return dict(execution_model=NextBarExecutionModel(price_field="open", delay_bars=1), slippage_model=FixedPercentSlippage(0.001), cost_model=PerShareCommission(0.005), spread_model=FixedPercentSpreadModel(0.001), position_sizer=FixedQuantitySizer(QUANTITY), risk_adapter=_risk_adapter())


def _trades_in_range(trades: Sequence[BacktestTrade], start: date, end: date) -> list[BacktestTrade]:
    return [t for t in trades if start <= t.entry_timestamp.date() <= end]


def _date_scoped_cost_sensitivity(*, strategy, bars_by_symbol, config, window_start: date, window_end: date) -> CostSensitivityReport:
    """Same 1x/2x/3x scenario shape as src.research.validation.run_cost_sensitivity,
    but restricted to trades ENTERED within [window_start, window_end] —
    needed because the input bars carry lookback context before the
    holdout window starts, and only trades actually entered inside the
    holdout should count toward the holdout's cost-sensitivity verdict."""
    m = _models()
    points = []
    for mult in (1.0, 2.0, 3.0):
        result = run_research_backtest(
            research_strategy=strategy, bars_by_symbol=bars_by_symbol, config=config, execution_model=m["execution_model"],
            slippage_model=_ScaledSlippageModel(m["slippage_model"], mult), cost_model=_ScaledCostModel(m["cost_model"], mult),
            spread_model=m["spread_model"], position_sizer=m["position_sizer"], risk_adapter=m["risk_adapter"],
        )
        scoped = _trades_in_range(result.trades, window_start, window_end)
        net_total = sum(t.net_pnl for t in scoped)
        points.append(CostSensitivityPoint(cost_multiplier=mult, slippage_multiplier=mult, trade_count=len(scoped), net_pnl_total=net_total, viable=net_total > 0))
    by_mult = {p.cost_multiplier: p.viable for p in points}
    return CostSensitivityReport(points=tuple(points), viable_at_base=by_mult.get(1.0), viable_at_2x=by_mult.get(2.0), viable_at_3x=by_mult.get(3.0))


def _date_scoped_execution_robustness(*, strategy, bars_by_symbol, config, window_start: date, window_end: date) -> ExecutionRobustnessReport:
    """Same 4-scenario shape as run_execution_robustness_extended, date-scoped
    the same way as _date_scoped_cost_sensitivity above."""
    m = _models()
    scenarios = [
        ("BASE (next-bar open)", m["execution_model"], m["slippage_model"], m["cost_model"]),
        ("STRESS 1 (extra execution delay, +1 bar)", NextBarExecutionModel(price_field="open", delay_bars=2), m["slippage_model"], m["cost_model"]),
        ("STRESS 2 (higher slippage, 2x)", m["execution_model"], _ScaledSlippageModel(m["slippage_model"], 2.0), m["cost_model"]),
        ("STRESS 3 (combined: +1 bar delay AND 2x slippage)", NextBarExecutionModel(price_field="open", delay_bars=2), _ScaledSlippageModel(m["slippage_model"], 2.0), m["cost_model"]),
    ]
    points = []
    for label, execution_model, slippage_model, cost_model in scenarios:
        result = run_research_backtest(research_strategy=strategy, bars_by_symbol=bars_by_symbol, config=config, execution_model=execution_model, slippage_model=slippage_model, cost_model=cost_model, spread_model=m["spread_model"], position_sizer=m["position_sizer"], risk_adapter=m["risk_adapter"])
        scoped = _trades_in_range(result.trades, window_start, window_end)
        net_total = sum(t.net_pnl for t in scoped)
        points.append(ExecutionRobustnessPoint(scenario=label, trade_count=len(scoped), net_pnl_total=net_total, viable=net_total > 0))
    return ExecutionRobustnessReport(points=tuple(points))


def _analyze(*, label: str, universe, strategy, trades: list[BacktestTrade], metrics, bars_by_symbol, cost_report, exec_report, regime_labels, pass_criteria: HoldoutPassCriteria, has_equity_curve: bool) -> dict:
    print(f"\n{'=' * 90}\n{label}\n{'=' * 90}", flush=True)
    print(f"Trade count: {len(trades)}", flush=True)
    if not trades:
        print("Zero trades — every downstream analysis below is vacuous for this holdout.", flush=True)
    if not has_equity_curve:
        print("NOTE: this holdout's trades were isolated by date from a longer continuous run (development+holdout "
              "combined, for feature lookback). There is no holdout-scoped equity curve, so CAGR/annualized "
              "return/volatility/Sharpe/Sortino/Calmar/max-drawdown/drawdown-duration below are UNAVAILABLE (not "
              "zero) — reported as such rather than computed from a misleading equity curve that includes "
              "development-period P&L. Trade-level statistics (expectancy, win rate, profit factor, distribution, "
              "concentration, etc.) are genuine and holdout-only.", flush=True)

    net_pnl_total = sum(t.net_pnl for t in trades)
    gross_pnl_total = sum(t.gross_pnl for t in trades)
    fees_total = sum(t.fees for t in trades)
    slippage_total = sum(t.slippage for t in trades)
    print(f"Gross P&L: ${gross_pnl_total:.2f}  Fees: ${fees_total:.2f}  Slippage: ${slippage_total:.2f}  Net P&L: ${net_pnl_total:.2f}", flush=True)
    print(f"Expectancy: ${metrics.trades.expectancy:.2f}/trade  Win rate: {metrics.trades.win_rate:.2%}  Profit factor: {metrics.trades.profit_factor}", flush=True)
    print(f"Avg win: ${metrics.trades.average_win:.2f}  Avg loss: ${metrics.trades.average_loss:.2f}  Largest win: ${metrics.trades.largest_win:.2f}  Largest loss: ${metrics.trades.largest_loss:.2f}", flush=True)
    print(f"Avg holding period: {metrics.trades.average_holding_period_minutes:.1f} min", flush=True)
    if has_equity_curve:
        print(f"Total return: {metrics.returns.total_return_pct}%  CAGR: {metrics.returns.cagr_pct}%  Annualized return: {metrics.returns.annualized_return_pct}%", flush=True)
        print(f"Volatility (ann.): {metrics.returns.volatility_annualized_pct}%  Sharpe: {metrics.returns.sharpe_ratio}  Sortino: {metrics.returns.sortino_ratio}  Calmar: {metrics.returns.calmar_ratio}", flush=True)
        print(f"Max drawdown: {metrics.drawdown.max_drawdown_pct}% (${metrics.drawdown.max_drawdown_usd:.2f})  Duration: {metrics.drawdown.max_drawdown_duration_bars} bars", flush=True)
        print(f"Portfolio: avg exposure={metrics.portfolio.average_exposure_pct}%  max exposure={metrics.portfolio.max_exposure_pct}%  turnover={metrics.portfolio.turnover}  max concurrent={metrics.portfolio.max_concurrent_positions}  max concentration={metrics.portfolio.max_concentration_pct}%", flush=True)
    else:
        print("Total return / CAGR / annualized return / volatility / Sharpe / Sortino / Calmar / max drawdown / drawdown duration / portfolio exposure: N/A (no holdout-scoped equity curve — see NOTE above)", flush=True)

    dist = trade_return_distribution(trades)
    print(f"Distribution: mean=${dist.mean:.2f} median=${dist.median:.2f} stdev={dist.stdev}", flush=True)
    print(f"  p5=${dist.p5:.2f} p25=${dist.p25:.2f} p50=${dist.p50:.2f} p75=${dist.p75:.2f} p95=${dist.p95:.2f}", flush=True)
    print(f"  top1%_of_trades_pnl_share={dist.pct_pnl_from_top_1pct_trades}%  top5%_of_trades_pnl_share={dist.pct_pnl_from_top_5pct_trades}%", flush=True)
    print(f"  largest_contributing_symbol={dist.largest_contributing_symbol} share={dist.pct_pnl_from_largest_contributing_symbol}%", flush=True)

    conc = concentration_summary(trades)
    print(f"Symbol concentration (fraction of net P&L): {sorted(conc.items(), key=lambda kv: abs(kv[1]), reverse=True)}", flush=True)

    if trades:
        loo = leave_one_symbol_out(trades, starting_cash=STARTING_CASH)
        print(f"Leave-one-out: max_expectancy_swing={loo.max_expectancy_swing} sign_flips_without={loo.sign_flips_without}", flush=True)
    else:
        loo = None

    sector_breakdown = by_sector(trades, universe, starting_cash=STARTING_CASH) if trades else {}
    print("By sector: " + "; ".join(f"{s}=${r.net_pnl_total:.0f}(n={r.trade_count})" for s, r in sector_breakdown.items()), flush=True)
    symbol_breakdown = by_symbol(trades, starting_cash=STARTING_CASH) if trades else {}
    print("By symbol: " + "; ".join(f"{s}=${r.net_pnl_total:.0f}(n={r.trade_count})" for s, r in symbol_breakdown.items()), flush=True)
    year_breakdown = by_year(trades, starting_cash=STARTING_CASH) if trades else {}
    print("By year: " + "; ".join(f"{y}=${r.net_pnl_total:.0f}(n={r.trade_count})" for y, r in year_breakdown.items()), flush=True)
    max_year_share_pct = None
    if year_breakdown and net_pnl_total != 0:
        max_year_share_pct = max(abs(r.net_pnl_total) for r in year_breakdown.values()) / abs(net_pnl_total) * 100

    regime_buckets = bucket_trades_by_regime(trades, regime_labels) if trades else {}
    regime_report = regime_performance_report(regime_buckets, starting_cash=STARTING_CASH) if trades else {}
    print("By regime: " + "; ".join(f"{r}=${m.trades.expectancy:.2f}/trade(n={m.trades.trade_count}) wr={m.trades.win_rate:.2%} pf={m.trades.profit_factor}" for r, m in regime_report.items()), flush=True)

    print(f"Cost sensitivity: 1x={cost_report.viable_at_base} 2x={cost_report.viable_at_2x} 3x={cost_report.viable_at_3x}", flush=True)
    for p in cost_report.points:
        print(f"  {p.cost_multiplier}x: trades={p.trade_count} net_pnl_total=${p.net_pnl_total:.2f} viable={p.viable}", flush=True)
    print(f"Execution robustness: fraction_viable={exec_report.fraction_viable}", flush=True)
    for p in exec_report.points:
        print(f"  {p.scenario}: trades={p.trade_count} net_pnl_total=${p.net_pnl_total:.2f} viable={p.viable}", flush=True)

    placebo = randomized_entry_timing_placebo(observed_trades=trades, bars_by_symbol=bars_by_symbol, holding_period_bars=strategy.spec.holding_period_bars, quantity=QUANTITY, n_trials=200, seed=42) if trades else None
    if placebo:
        print(f"Placebo (entry-timing): n_trials={placebo.n_trials} seed={placebo.seed} observed={placebo.observed_statistic:.4f} fraction_as_extreme_or_better={placebo.fraction_as_extreme_or_better}", flush=True)

    permutation = random_symbol_and_timing_placebo(observed_trades=trades, bars_by_symbol=bars_by_symbol, holding_period_bars=strategy.spec.holding_period_bars, quantity=QUANTITY, n_trials=200, seed=43) if trades else None
    if permutation:
        print(f"Permutation (symbol+timing): n_trials={permutation.n_trials} seed={permutation.seed} observed={permutation.observed_statistic:.4f} fraction_as_extreme_or_better={permutation.fraction_as_extreme_or_better}", flush=True)

    bootstrap = bootstrap_trade_statistics(trades, n_resamples=1000, seed=42)
    print(bootstrap.render(), flush=True)

    max_symbol_share_pct = max((abs(v) for v in conc.values()), default=None)
    if max_symbol_share_pct is not None:
        max_symbol_share_pct *= 100

    evaluation = evaluate_pass_criteria(
        pass_criteria, trade_count=len(trades), expectancy=metrics.trades.expectancy, net_pnl_total=net_pnl_total,
        max_drawdown_pct=metrics.drawdown.max_drawdown_pct if has_equity_curve else None,
        profit_factor=metrics.trades.profit_factor,
        max_symbol_pnl_share_pct=max_symbol_share_pct,
        top_5pct_trades_pnl_share_pct=dist.pct_pnl_from_top_5pct_trades,
        viable_at_2x_costs=cost_report.viable_at_2x, viable_under_extra_execution_delay=exec_report.points[1].viable if len(exec_report.points) > 1 else None,
        max_year_pnl_share_pct=max_year_share_pct,
    )
    print("\n" + evaluation.render(), flush=True)

    classification = classify_strategy(oos_metrics=metrics, in_sample_metrics=None, parameter_stability=None, cost_sensitivity=cost_report, robustness=None)
    print(f"\nCLASSIFICATION: {classification.classification.value}", flush=True)
    for r in classification.reasons:
        print(f"  - {r}", flush=True)

    gate = determine_gate_stage(
        strategy_id=strategy.spec.strategy_id, strategy_version="1.0", classification=classification,
        pass_criteria_evaluation=evaluation, holdout_trade_count=len(trades), min_trade_count_for_a_verdict=MIN_OOS_TRADES_FOR_A_VERDICT,
    )
    print("\n" + gate.render(), flush=True)

    return dict(
        trade_count=len(trades), net_pnl_total=net_pnl_total, gross_pnl_total=gross_pnl_total, fees_total=fees_total, slippage_total=slippage_total,
        metrics=metrics, distribution=dist, concentration=conc, leave_one_out=loo, sector_breakdown=sector_breakdown, symbol_breakdown=symbol_breakdown,
        year_breakdown=year_breakdown, regime_report=regime_report, cost_report=cost_report, exec_report=exec_report, placebo=placebo,
        permutation=permutation, bootstrap=bootstrap, evaluation=evaluation, classification=classification, gate=gate,
    )


def main() -> None:
    frozen_store = FrozenStrategyStore(Path("logs/research_data/frozen_strategies.jsonl"))
    frozen = frozen_store.get("MR-002", "1.0")
    if frozen is None:
        raise RuntimeError("MR-002 1.0 is not frozen — run scripts/phase6_step1_freeze_mr002.py first.")
    print(f"Running FROZEN {frozen.strategy_id} {frozen.strategy_version} (content_hash={frozen.content_hash()[:16]})", flush=True)

    holdout_path = Path("logs/research_data/phase6_holdout_period.json")
    if not holdout_path.is_file():
        raise RuntimeError("holdout period not computed — run scripts/phase6_step2_determine_holdout.py first.")
    hp = json.loads(holdout_path.read_text())
    dev_start, dev_end = date.fromisoformat(hp["development_start"]), date.fromisoformat(hp["development_end"])
    holdout_start, holdout_end = date.fromisoformat(hp["holdout_start"]), date.fromisoformat(hp["holdout_end"])
    print(f"Development: {dev_start}..{dev_end}   Holdout: {holdout_start}..{holdout_end}", flush=True)

    criteria_path = Path("logs/research_data/phase6_pass_criteria.json")
    if not criteria_path.is_file():
        raise RuntimeError("pass criteria not pre-registered — run scripts/phase6_step3_define_pass_criteria.py first.")
    pass_criteria = HoldoutPassCriteria.from_dict(json.loads(criteria_path.read_text()))
    print(f"Pass criteria pre-registered at: {pass_criteria.pre_registered_at}", flush=True)

    store = HistoricalDataStore(Path("logs/research_data"))
    exp_store = ExperimentStore(Path("logs/research_data/experiments.jsonl"))

    # ---------------------------------------------------------------- PRIMARY: temporal holdout on US_DIVERSIFIED
    primary_universe = us_diversified_universe()
    primary_quality = run_universe_quality_report(store, primary_universe, "day", min_bars_required=100)
    primary_usable = [s.symbol for s in primary_quality if s.available]
    print(f"\nPRIMARY universe {primary_universe.name}: {len(primary_usable)}/{len(primary_universe.symbols)} usable. "
          f"Survivorship-bias status: {primary_universe.survivorship_bias_status}", flush=True)

    primary_bars_full = {s: store.load(s, "day") for s in primary_usable}
    primary_bars_dev_to_holdout = filter_bars_by_date(primary_bars_full, start=dev_start, end=holdout_end)
    primary_strategy = build_strategy_from_frozen(frozen, primary_usable)
    primary_config = BacktestConfig(symbols=tuple(primary_usable), timeframe="day", start=dev_start, end=holdout_end, data_version="phase6-holdout-v1", feature_version="phase6-holdout-v1", initial_capital_usd=STARTING_CASH)

    m = _models()
    primary_full_result = run_research_backtest(research_strategy=primary_strategy, bars_by_symbol=primary_bars_dev_to_holdout, config=primary_config, **m)
    primary_holdout_trades = _trades_in_range(primary_full_result.trades, holdout_start, holdout_end)
    primary_metrics = compute_performance_metrics(equity_curve=[], trades=primary_holdout_trades, starting_cash=STARTING_CASH)
    print(f"\n(Diagnostic, not a re-run: the same single backtest over {dev_start}..{holdout_end} produced "
          f"{len(primary_full_result.trades)} total trades, of which {len(primary_holdout_trades)} entered inside "
          f"the holdout window — the rest are development-period trades from the same continuous run, kept only for "
          f"feature lookback and discarded from the holdout verdict.)", flush=True)

    primary_regime_labels: dict = {}
    for s in primary_usable:
        primary_regime_labels.update(label_bars_by_regime(primary_bars_full[s]))

    primary_cost = _date_scoped_cost_sensitivity(strategy=primary_strategy, bars_by_symbol=primary_bars_dev_to_holdout, config=primary_config, window_start=holdout_start, window_end=holdout_end)
    primary_exec = _date_scoped_execution_robustness(strategy=primary_strategy, bars_by_symbol=primary_bars_dev_to_holdout, config=primary_config, window_start=holdout_start, window_end=holdout_end)

    primary_result = _analyze(
        label=f"PRIMARY HOLDOUT — {primary_universe.name}, {holdout_start}..{holdout_end} (temporal, never touched by any Phase 4/5 train/validation/test window)",
        universe=primary_universe, strategy=primary_strategy, trades=primary_holdout_trades, metrics=primary_metrics,
        bars_by_symbol=primary_bars_dev_to_holdout, cost_report=primary_cost, exec_report=primary_exec,
        regime_labels=primary_regime_labels, pass_criteria=pass_criteria, has_equity_curve=False,
    )

    primary_experiment = exp_store.record(
        data_version=primary_config.data_version, feature_version=primary_config.feature_version, symbols=primary_usable, timeframe="day",
        strategy_version=frozen.strategy_version, prediction_horizon=frozen.prediction_horizon_bars,
        train_period=(dev_start.isoformat(), dev_end.isoformat()), test_period=(holdout_start.isoformat(), holdout_end.isoformat()),
        parameters={"lookback": frozen.lookback, "entry_z": frozen.entry_threshold, "exit_z": frozen.exit_threshold},
        metrics={"holdout_trade_count": primary_result["trade_count"], "holdout_expectancy": primary_metrics.trades.expectancy},
        strategy_family="mean_reversion", classification=primary_result["classification"].classification.value,
        oos_metrics={"trade_count": primary_result["trade_count"], "win_rate": primary_metrics.trades.win_rate, "expectancy": primary_metrics.trades.expectancy, "profit_factor": primary_metrics.trades.profit_factor},
        cost_sensitivity={"points": [{"cost_multiplier": p.cost_multiplier, "viable": p.viable, "net_pnl_total": p.net_pnl_total} for p in primary_cost.points]},
        tags=("phase6-holdout", "primary-temporal-holdout", primary_universe.name), notes="; ".join(primary_result["classification"].reasons),
        hypothesis_id="MR-002", universe_name=primary_universe.name,
    )
    print(f"\nRecorded PRIMARY holdout experiment: {primary_experiment.experiment_id}", flush=True)

    # -------------------------------------------------------------- SECONDARY: full-history holdout on a brand-new universe
    secondary_universe = us_diversified_secondary_universe()
    secondary_quality = run_universe_quality_report(store, secondary_universe, "day", min_bars_required=100)
    secondary_usable = [s.symbol for s in secondary_quality if s.available]
    print(f"\nSECONDARY universe {secondary_universe.name}: {len(secondary_usable)}/{len(secondary_universe.symbols)} usable. "
          f"Survivorship-bias status: {secondary_universe.survivorship_bias_status}", flush=True)

    secondary_bars = {s: store.load(s, "day") for s in secondary_usable}
    secondary_start = min(b[0].timestamp.date() for b in secondary_bars.values() if b)
    secondary_end = max(b[-1].timestamp.date() for b in secondary_bars.values() if b)
    secondary_strategy = build_strategy_from_frozen(frozen, secondary_usable)
    secondary_config = BacktestConfig(symbols=tuple(secondary_usable), timeframe="day", start=secondary_start, end=secondary_end, data_version="phase6-holdout-v1", feature_version="phase6-holdout-v1", initial_capital_usd=STARTING_CASH)

    secondary_full_result = run_research_backtest(research_strategy=secondary_strategy, bars_by_symbol=secondary_bars, config=secondary_config, **m)
    secondary_trades = list(secondary_full_result.trades)
    secondary_metrics = secondary_full_result.metrics  # a genuine continuous equity curve — the whole run IS the holdout

    secondary_regime_labels: dict = {}
    for s in secondary_usable:
        secondary_regime_labels.update(label_bars_by_regime(secondary_bars[s]))

    secondary_cost = run_cost_sensitivity(research_strategy=secondary_strategy, bars_by_symbol=secondary_bars, config=secondary_config, execution_model=m["execution_model"], base_slippage_model=m["slippage_model"], base_cost_model=m["cost_model"], spread_model=m["spread_model"], position_sizer=m["position_sizer"], risk_adapter=m["risk_adapter"])
    secondary_exec = run_execution_robustness_extended(research_strategy=secondary_strategy, bars_by_symbol=secondary_bars, config=secondary_config, base_execution_model=m["execution_model"], base_slippage_model=m["slippage_model"], base_cost_model=m["cost_model"], spread_model=m["spread_model"], position_sizer=m["position_sizer"], risk_adapter=m["risk_adapter"])

    secondary_result = _analyze(
        label=f"SECONDARY HOLDOUT — {secondary_universe.name}, {secondary_start}..{secondary_end} (entirely new universe, never touched by any Phase 4/5/6 tuning)",
        universe=secondary_universe, strategy=secondary_strategy, trades=secondary_trades, metrics=secondary_metrics,
        bars_by_symbol=secondary_bars, cost_report=secondary_cost, exec_report=secondary_exec,
        regime_labels=secondary_regime_labels, pass_criteria=pass_criteria, has_equity_curve=True,
    )

    secondary_experiment = exp_store.record(
        data_version=secondary_config.data_version, feature_version=secondary_config.feature_version, symbols=secondary_usable, timeframe="day",
        strategy_version=frozen.strategy_version, prediction_horizon=frozen.prediction_horizon_bars,
        test_period=(secondary_start.isoformat(), secondary_end.isoformat()),
        parameters={"lookback": frozen.lookback, "entry_z": frozen.entry_threshold, "exit_z": frozen.exit_threshold},
        metrics={"holdout_trade_count": secondary_result["trade_count"], "holdout_expectancy": secondary_metrics.trades.expectancy},
        strategy_family="mean_reversion", classification=secondary_result["classification"].classification.value,
        oos_metrics={"trade_count": secondary_result["trade_count"], "win_rate": secondary_metrics.trades.win_rate, "expectancy": secondary_metrics.trades.expectancy, "profit_factor": secondary_metrics.trades.profit_factor},
        cost_sensitivity={"points": [{"cost_multiplier": p.cost_multiplier, "viable": p.viable, "net_pnl_total": p.net_pnl_total} for p in secondary_cost.points]},
        tags=("phase6-holdout", "secondary-universe-holdout", secondary_universe.name), notes="; ".join(secondary_result["classification"].reasons),
        hypothesis_id="MR-002", universe_name=secondary_universe.name,
    )
    print(f"\nRecorded SECONDARY holdout experiment: {secondary_experiment.experiment_id}", flush=True)

    # -------------------------------------------------------------------------------------------------- final summary
    print(f"\n{'=' * 90}\nPHASE 6 SUMMARY\n{'=' * 90}", flush=True)
    print(f"PRIMARY  ({primary_universe.name}, temporal, n={primary_result['trade_count']}): classification={primary_result['classification'].classification.value}  gate={primary_result['gate'].stage.value}", flush=True)
    print(f"SECONDARY ({secondary_universe.name}, full-history, n={secondary_result['trade_count']}): classification={secondary_result['classification'].classification.value}  gate={secondary_result['gate'].stage.value}", flush=True)

    print("\nMultiple-testing accounting (this phase added exactly 2 new experiments: 1 primary temporal holdout, "
          "1 secondary universe holdout — zero parameter sweeps, zero strategy variants, zero re-runs):", flush=True)
    print(compute_search_space_summary(exp_store.load_all()).render(), flush=True)


if __name__ == "__main__":
    main()
