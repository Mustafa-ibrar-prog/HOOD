#!/usr/bin/env python3
"""Phase 8, Parts 4-5, 20 — STEP 2: runs the FULL preregistered 18-variant
parameter grid for P7-VOLANOM-A-DEV1 on DISCOVERY_DATA+DEVELOPMENT_DATA
only, records every variant (failures included, nothing hidden), and
reports the complete parameter surface. Also builds the variant-return
matrix (8 equal-width sub-periods, shared across variants) used by
scripts/phase8_step3_deep_dive_anchor.py's PBO/effective-trials analysis.

No parameter is "selected" here — this script only measures and reports
the whole grid.
"""

from __future__ import annotations

import json
import sys
from datetime import date, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtesting import (  # noqa: E402
    BacktestConfig,
    BacktestRiskAdapter,
    FixedDollarSizer,
    FixedPercentSlippage,
    FixedPercentSpreadModel,
    NextBarExecutionModel,
    PerShareCommission,
)
from src.data import HistoricalDataStore, run_universe_quality_report, us_diversified_universe  # noqa: E402
from src.risk.manager import RiskManager  # noqa: E402
from src.risk.models import RiskLimits  # noqa: E402
from src.research import (  # noqa: E402
    ExperimentStore,
    PartitionLifecycleStage,
    PartitionStore,
    VolumeAnomalyLongStrategy,
    require_preregistered,
    run_research_backtest,
)
from src.research.preregistration import PreregistrationStore

DOLLARS_PER_POSITION = 2_000.0  # equal-dollar sizing (Part 9) — same amount regardless of price, so no symbol dominates via price level alone
STARTING_CASH = 100_000.0
PBO_N_PERIODS = 8  # small, CSCV-tractable (C(8,4)=70 combinations), even (required)

BASELINE_LOOKBACK_GRID = (10, 20)
ANOMALY_THRESHOLD_GRID = (1.5, 2.0, 3.0)
HOLDING_PERIOD_GRID = (3, 5, 10)
ANCHOR = {"baseline_lookback": 10, "anomaly_threshold": 2.0, "holding_period_bars": 5}  # matches the PARENT discovery feature exactly + the median of each newly-introduced axis — fixed BEFORE any backtest ran


def _risk_adapter() -> BacktestRiskAdapter:
    limits = RiskLimits(max_trades_per_day=10, max_daily_loss_usd=1_000_000.0, max_position_size_usd=20_000.0, cooldown_minutes_after_exit=0, stale_data_max_seconds=10**9, max_spread_pct=1.0, min_option_volume=0, min_option_open_interest=0, max_extended_move_pct=100.0, entry_cutoff_time=time(23, 59))
    return BacktestRiskAdapter(RiskManager(limits))


def _models():
    return dict(execution_model=NextBarExecutionModel(price_field="open", delay_bars=1), slippage_model=FixedPercentSlippage(0.001), cost_model=PerShareCommission(0.005), spread_model=FixedPercentSpreadModel(0.001), position_sizer=FixedDollarSizer(DOLLARS_PER_POSITION), risk_adapter=_risk_adapter())


def strategy_factory(params: dict, usable_symbols: list[str]):
    return VolumeAnomalyLongStrategy(strategy_id="P7-VOLANOM-A-DEV1", baseline_lookback=params["baseline_lookback"], anomaly_threshold=params["anomaly_threshold"], holding_period_bars=params["holding_period_bars"], universe=usable_symbols)


def period_bucket(d: date, dev_start: date, dev_end: date, n_periods: int) -> int:
    total_days = (dev_end - dev_start).days + 1
    day_offset = (d - dev_start).days
    bucket = min(n_periods - 1, (day_offset * n_periods) // total_days)
    return max(0, bucket)


def main() -> None:
    store = HistoricalDataStore(Path("logs/research_data"))
    universe = us_diversified_universe()

    prereg_store = PreregistrationStore(Path("logs/research_data/phase8_preregistrations.jsonl"))
    require_preregistered(prereg_store, "P7-VOLANOM-A-DEV1")  # STRUCTURAL enforcement

    partition_store = PartitionStore(Path("logs/research_data/phase7_partitions.jsonl"))
    discovery = partition_store.active_by_stage(PartitionLifecycleStage.DISCOVERY)[0]
    development = partition_store.active_by_stage(PartitionLifecycleStage.DEVELOPMENT)[0]
    dev_start, dev_end = discovery.start_date, development.end_date

    quality = run_universe_quality_report(store, universe, "day", min_bars_required=100)
    usable = [s.symbol for s in quality if s.available]
    unusable = [s.symbol for s in quality if not s.available]
    print(f"DEVELOPMENT DATASET: {dev_start} .. {dev_end}", flush=True)
    print(f"Universe: {universe.name}  usable={len(usable)}/{len(universe.symbols)}  unusable={unusable}", flush=True)
    for q in quality:
        issue_counts = q.quality_report.counts_by_code if q.quality_report else {}
        print(f"  {q.symbol}: available={q.available} bars={q.bar_count} date_range={q.date_range} issues={issue_counts}", flush=True)

    bars_by_symbol_full = {s: store.load(s, "day") for s in usable}
    bars_by_symbol_dev = {s: [b for b in bars if dev_start <= b.timestamp.date() <= dev_end] for s, bars in bars_by_symbol_full.items()}
    total_obs = sum(len(b) for b in bars_by_symbol_dev.values())
    print(f"Total development observations (bar-days across universe): {total_obs}", flush=True)

    config = BacktestConfig(symbols=tuple(usable), timeframe="day", start=dev_start, end=dev_end, data_version="phase5-campaign-v1", feature_version="phase8-dev-v1", initial_capital_usd=STARTING_CASH)
    m = _models()
    exp_store = ExperimentStore(Path("logs/research_data/experiments.jsonl"))

    combos = [{"baseline_lookback": bl, "anomaly_threshold": at, "holding_period_bars": hp} for bl in BASELINE_LOOKBACK_GRID for at in ANOMALY_THRESHOLD_GRID for hp in HOLDING_PERIOD_GRID]
    assert len(combos) == 18
    is_anchor = lambda p: p == ANCHOR  # noqa: E731

    print(f"\n{'=' * 90}\nFULL PARAMETER GRID ({len(combos)} variants) — every variant reported, none hidden\n{'=' * 90}", flush=True)

    variant_results = []
    period_matrix: list[list[float]] = []
    for i, params in enumerate(combos):
        strategy = strategy_factory(params, usable)
        result = run_research_backtest(research_strategy=strategy, bars_by_symbol=bars_by_symbol_dev, config=config, **m)
        trades = result.trades
        net_total = sum(t.net_pnl for t in trades)
        gross_total = sum(t.gross_pnl for t in trades)
        expectancy = (net_total / len(trades)) if trades else 0.0
        win_rate = (sum(1 for t in trades if t.net_pnl > 0) / len(trades)) if trades else 0.0

        periods = [0.0] * PBO_N_PERIODS
        for t in trades:
            periods[period_bucket(t.entry_timestamp.date(), dev_start, dev_end, PBO_N_PERIODS)] += t.net_pnl
        period_matrix.append(periods)

        anchor_flag = " <-- ANCHOR" if is_anchor(params) else ""
        print(f"[{i:2d}] lookback={params['baseline_lookback']:2d} thresh={params['anomaly_threshold']:.1f} hold={params['holding_period_bars']:2d}bars  "
              f"trades={len(trades):4d} gross=${gross_total:9.2f} net=${net_total:9.2f} expectancy=${expectancy:7.2f} win_rate={win_rate:.2%}{anchor_flag}", flush=True)

        exp_store.record(
            data_version=config.data_version, feature_version=config.feature_version, symbols=usable, timeframe="day",
            strategy_version="1.0", prediction_horizon=5, train_period=(str(dev_start), str(dev_end)), parameters=params,
            metrics={"trade_count": len(trades), "gross_pnl_total": gross_total, "net_pnl_total": net_total, "expectancy": expectancy, "win_rate": win_rate},
            strategy_family="volume_anomaly", classification="GRID_POINT_NOT_YET_CLASSIFIED", tags=("phase8-dev-grid", universe.name),
            notes="raw parameter-grid point — anchor-variant deep-dive classifies the hypothesis, not individual grid points",
            hypothesis_id="P7-VOLANOM-A-DEV1", universe_name=universe.name, research_family_id="P8-VOLANOM-DEV-GRID-2026-09",
        )
        variant_results.append({"params": params, "trade_count": len(trades), "net_pnl_total": net_total, "gross_pnl_total": gross_total, "expectancy": expectancy, "win_rate": win_rate})

    out_path = Path("logs/research_data/phase8_grid_results.json")
    out_path.write_text(json.dumps({"dev_start": str(dev_start), "dev_end": str(dev_end), "usable_symbols": usable, "variants": variant_results, "period_matrix": period_matrix, "anchor": ANCHOR}, indent=2))
    print(f"\nWritten to {out_path}", flush=True)

    n_positive = sum(1 for v in variant_results if v["net_pnl_total"] > 0)
    print(f"\nSUMMARY: {n_positive}/{len(variant_results)} variants net-profitable (gross of the deeper robustness checks below).", flush=True)


if __name__ == "__main__":
    main()
