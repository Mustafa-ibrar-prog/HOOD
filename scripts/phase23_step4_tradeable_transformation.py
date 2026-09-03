#!/usr/bin/env python3
"""Phase 23, STEP 4 — Parts 7, 8, 16, 17, 18, 20 (comparison), 21: the
P23-OPT-013-TRADEABLE rule-based transformation. Converts the frozen
P22-OPT-013 discovery relationship into the simplest possible tradeable
rule -- IF option_range_expansion_5 > threshold THEN enter long the
option -- over the small, preregistered grid from step 2, with a
REALISTIC entry (never the same bar whose own high/low produced the
signal -- Part 8's explicit prohibition on an impossible fill).

The PRIMARY grid point for the deep-dive cost/feasibility/sizing
analysis (threshold=1.75, holding_period=5, entry=next_bar_open) was
chosen HERE, before this script's first run, on principled grounds
(median threshold, the parent hypothesis's own horizon, the most
conservative entry timing) -- not selected after seeing which grid cell
performed best. This is not a change to step 2's preregistered grid,
only a documented choice of where to spend the deeper analysis Part
16-18 ask for.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.options.cost_model import COST_SENSITIVITY_ASSUMPTIONS, FIVE_X_ASSUMPTION, apply_cost_assumption  # noqa: E402
from src.options.outlier_treatment import compute_outlier_attribution, top_observations, winsorize  # noqa: E402
from src.options.price_history import OptionPriceBar  # noqa: E402
from src.research import (  # noqa: E402
    ExperimentStore,
    benjamini_hochberg_fdr,
    bonferroni_correction,
    deflated_sharpe_ratio,
    holm_bonferroni_correction,
    probability_of_backtest_overfitting,
    require_preregistered,
)
from src.research.analysis import mean as _mean  # noqa: E402
from src.research.analysis import stdev as _stdev  # noqa: E402
from src.research.experiment_fingerprint import ExperimentDimensions, compute_experiment_fingerprint  # noqa: E402
from src.research.preregistration import PreregistrationStore  # noqa: E402
from src.research.stats_utils import t_test_p_value  # noqa: E402
from src.options.universe import phase20_verified_underlying_universe  # noqa: E402

PANEL_PATH = Path("logs/research_data/phase23_research_panel.jsonl")
FEATURE = "option_range_expansion_5"
INV_ID = "P23-OPT-013-TRADEABLE"

THRESHOLD_GRID = (1.25, 1.50, 1.75, 2.00, 2.50)
HOLDING_PERIOD_GRID = (1, 3, 5, 10)
ENTRY_TIMING_VARIANTS = ("next_bar_open", "next_bar_close")
PRIMARY = {"threshold": 1.75, "holding_period": 5, "entry_timing": "next_bar_open"}  # chosen BEFORE this run -- see module docstring
ACCOUNT_SIZE = 1000.0
CONTRACT_MULTIPLIER = 100
MIN_ENTRY_PRICE = 0.05  # excludes the $0.01 tick-floor-pinned artifact Phase 19's find_suspicious_flat_price_run
# already documented (is_flat_pinned) -- a $0.01 entry is not a realistic, fillable price; a handful of these
# produce mathematically enormous (exit/0.01) percentage "returns" that are a data-mechanics artifact, not a
# real trading opportunity. Excluded by an explicit price floor, not silently left in to inflate the mean.


def _fmt(x) -> str:
    return "None" if x is None else f"{x:.5f}"


def load_bars_by_contract() -> dict[str, list[dict]]:
    rows = [json.loads(line) for line in PANEL_PATH.read_text().splitlines() if line.strip()]
    rows = [r for r in rows if r.get("is_research_eligible")]
    by_contract: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_contract[r["option_id"]].append(r)
    for cid in by_contract:
        by_contract[cid] = sorted(by_contract[cid], key=lambda r: r["timestamp"])
    return by_contract


def simulate_trades(by_contract: dict[str, list[dict]], *, threshold: float, holding_period: int, entry_timing: str, first_signal_only: bool) -> list[dict]:
    """Every trade: signal observed at bar i (using bar i's own OHLC --
    permissible, since the DECISION is made at/after that bar's close);
    entry at bar i+1 (`entry_timing` picks open or close of the NEXT
    bar -- never bar i's own close, which would require knowing bar i's
    high/low, the very inputs that produced the signal, before they were
    fully observed in a live/tradable sense... actually bar i's close IS
    knowable at end-of-day i, but entering there risks using same-bar
    OHLC to justify a fill at a price already implicated in computing
    the signal -- Part 8 requires the NEXT bar); exit `holding_period`
    bars after entry, at that bar's close."""
    trades: list[dict] = []
    for cid, rows in by_contract.items():
        bars = [OptionPriceBar(date=date.fromisoformat(r["timestamp"]), open=r["option_open"], high=r["option_high"], low=r["option_low"], close=r["option_close"]) for r in rows]
        n = len(bars)
        in_cluster = False
        for i in range(n):
            feat = rows[i].get(FEATURE)
            signaled = feat is not None and feat > threshold
            if not signaled:
                in_cluster = False
                continue
            if first_signal_only and in_cluster:
                continue
            in_cluster = True
            entry_idx = i + 1
            exit_idx = entry_idx + holding_period
            if exit_idx >= n:
                continue
            entry_price = bars[entry_idx].open if entry_timing == "next_bar_open" else bars[entry_idx].close
            exit_price = bars[exit_idx].close
            if entry_price < MIN_ENTRY_PRICE:
                continue
            trades.append({
                "option_id": cid, "underlying_symbol": rows[i]["underlying_symbol"], "signal_date": rows[i]["timestamp"],
                "entry_price": entry_price, "exit_price": exit_price, "return": (exit_price - entry_price) / entry_price,
                "call_put": rows[i]["call_put"], "expiration": rows[i]["expiration"],
            })
    return trades


def summarize_trades(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "mean_return": None, "win_rate": None, "p_value": None, "stdev": None}
    returns = [t["return"] for t in trades]
    return {
        "n": len(trades), "mean_return": _mean(returns), "win_rate": sum(1 for r in returns if r > 0) / len(returns),
        "p_value": t_test_p_value(returns), "stdev": _stdev(returns) if len(returns) > 1 else None,
    }


def main() -> None:
    prereg_store = PreregistrationStore(Path("logs/research_data/phase23_preregistrations.jsonl"))
    require_preregistered(prereg_store, INV_ID)
    universe = phase20_verified_underlying_universe()

    by_contract = load_bars_by_contract()
    print(f"Loaded {len(by_contract)} contracts.\n", flush=True)
    print(f"PRIMARY grid point for deep-dive analysis (chosen before this run): {PRIMARY}\n", flush=True)

    # ============================================================== PART 7/8: GRID SCAN (every entry-timing variant)
    print(f"{'=' * 100}\nPART 7/8 — TRADEABLE-RULE GRID SCAN ({len(THRESHOLD_GRID)}x{len(HOLDING_PERIOD_GRID)}x{len(ENTRY_TIMING_VARIANTS)} combinations)\n{'=' * 100}", flush=True)
    raw_p_values: list[tuple[str, float]] = []
    grid_results: dict[tuple, dict] = {}
    positive_significant_cells = 0
    total_cells = 0
    for entry_timing in ENTRY_TIMING_VARIANTS:
        for threshold in THRESHOLD_GRID:
            for holding_period in HOLDING_PERIOD_GRID:
                trades = simulate_trades(by_contract, threshold=threshold, holding_period=holding_period, entry_timing=entry_timing, first_signal_only=False)
                summary = summarize_trades(trades)
                grid_results[(entry_timing, threshold, holding_period)] = summary
                total_cells += 1
                if summary["p_value"] is not None:
                    raw_p_values.append((f"grid|{entry_timing}|t={threshold}|h={holding_period}", summary["p_value"]))
                    if summary["mean_return"] > 0 and summary["p_value"] < 0.05:
                        positive_significant_cells += 1
                print(f"  [{entry_timing}] threshold={threshold} holding={holding_period}: n={summary['n']}  "
                      f"mean_return={_fmt(summary['mean_return'])}  win_rate={_fmt(summary['win_rate'])}  p={_fmt(summary['p_value'])}", flush=True)
    print(f"\n  {positive_significant_cells}/{total_cells} grid cells positive AND nominally significant (p<0.05, uncorrected).", flush=True)

    # ============================================================== PART 9 cross-check: first-signal-only at PRIMARY
    print(f"\n{'=' * 100}\nCROSS-CHECK: first-signal-only vs every-signal at the PRIMARY grid point\n{'=' * 100}", flush=True)
    every_signal_trades = simulate_trades(by_contract, threshold=PRIMARY["threshold"], holding_period=PRIMARY["holding_period"], entry_timing=PRIMARY["entry_timing"], first_signal_only=False)
    first_signal_trades = simulate_trades(by_contract, threshold=PRIMARY["threshold"], holding_period=PRIMARY["holding_period"], entry_timing=PRIMARY["entry_timing"], first_signal_only=True)
    every_summary = summarize_trades(every_signal_trades)
    first_summary = summarize_trades(first_signal_trades)
    print(f"  every-signal:      n={every_summary['n']}  mean_return={_fmt(every_summary['mean_return'])}  p={_fmt(every_summary['p_value'])}", flush=True)
    print(f"  first-signal-only: n={first_summary['n']}  mean_return={_fmt(first_summary['mean_return'])}  p={_fmt(first_summary['p_value'])}", flush=True)

    # ============================================================== PART 16: COST AND EXECUTION STRESS (on PRIMARY)
    print(f"\n{'=' * 100}\nPART 16 — COST AND EXECUTION STRESS (PRIMARY grid point, MARK_TO_MARKET_HISTORICAL_RESEARCH)\n{'=' * 100}", flush=True)
    primary_trades = every_signal_trades
    print(f"  PRIMARY: n_trades={len(primary_trades)}  gross mean_return={_fmt(every_summary['mean_return'])}", flush=True)
    cost_survives = []
    for assumption in list(COST_SENSITIVITY_ASSUMPTIONS) + [FIVE_X_ASSUMPTION]:
        net_returns = [apply_cost_assumption(t["return"], t["entry_price"], assumption) for t in primary_trades if t["entry_price"] > 0]
        net_mean = _mean(net_returns) if net_returns else None
        survives = net_mean is not None and net_mean > 0
        cost_survives.append(survives)
        print(f"  {assumption.label}: net_mean_return={_fmt(net_mean)}  survives={survives}", flush=True)
    cost_fragile = not cost_survives[0]
    print(f"  COST_FRAGILE (fails even 1x): {cost_fragile}", flush=True)

    print("\n  Execution stress (delayed entry/exit by 1 extra bar, PRIMARY threshold/holding):", flush=True)
    delayed_entry_trades = []
    for cid, rows in by_contract.items():
        bars = [OptionPriceBar(date=date.fromisoformat(r["timestamp"]), open=r["option_open"], high=r["option_high"], low=r["option_low"], close=r["option_close"]) for r in rows]
        n = len(bars)
        for i in range(n):
            feat = rows[i].get(FEATURE)
            if feat is None or feat <= PRIMARY["threshold"]:
                continue
            entry_idx = i + 2  # +1 extra bar delay vs the PRIMARY's i+1
            exit_idx = entry_idx + PRIMARY["holding_period"] + 1  # +1 extra bar delay on exit too
            if exit_idx >= n:
                continue
            entry_price = bars[entry_idx].open
            exit_price = bars[exit_idx].close
            if entry_price < MIN_ENTRY_PRICE:
                continue
            delayed_entry_trades.append({"return": (exit_price - entry_price) / entry_price, "entry_price": entry_price})
    delayed_summary = summarize_trades(delayed_entry_trades)
    print(f"  delayed entry(+1 bar) and exit(+1 bar): n={delayed_summary['n']}  mean_return={_fmt(delayed_summary['mean_return'])}  p={_fmt(delayed_summary['p_value'])}", flush=True)

    # ---- mandatory outlier check on the tradeable P&L itself (Part 13's outlier discipline, applied here too --
    # a MEAN-return-based P&L simulation is exactly the statistic that a handful of extreme winners can dominate,
    # unlike the rank-based IC the rest of Phase 19-23 primarily relies on) ----
    print(f"\n  Outlier check on PRIMARY trade returns (n={len(primary_trades)}):", flush=True)
    primary_returns = [t["return"] for t in primary_trades]
    trade_attribution = compute_outlier_attribution(primary_returns)
    median_return = sorted(primary_returns)[len(primary_returns) // 2]
    print(f"    mean={_fmt(_mean(primary_returns))}  median={_fmt(median_return)}  win_rate={_fmt(every_summary['win_rate'])}", flush=True)
    print(f"    top_1%_share={_fmt(trade_attribution.top_1pct_share)}  top_5%_share={_fmt(trade_attribution.top_5pct_share)}  top_10%_share={_fmt(trade_attribution.top_10pct_share)}", flush=True)
    top5_wins = top_observations(primary_returns, n=5, by="positive")
    print(f"    top 5 winning trades: {[f'{o.value:.3f}' for o in top5_wins]}", flush=True)
    winsorized_returns = winsorize(primary_returns, fraction=0.05)
    winsorized_mean = _mean(winsorized_returns)
    winsorized_p = t_test_p_value(winsorized_returns)
    print(f"    winsorize 5%: mean={_fmt(winsorized_mean)}  p={_fmt(winsorized_p)}", flush=True)
    trade_outlier_dependent = median_return <= 0 or winsorized_mean <= 0 or (trade_attribution.top_5pct_share or 0) > 0.75
    print(f"    TRADE_OUTLIER_DEPENDENT: {trade_outlier_dependent}  (median trade result {'is a LOSS' if median_return <= 0 else 'is a gain'} "
          f"despite a positive mean -- the positive mean is {'substantially' if trade_outlier_dependent else 'not primarily'} carried by a small "
          f"number of extreme winners)", flush=True)

    # ============================================================== PART 17: SMALL-ACCOUNT FEASIBILITY
    print(f"\n{'=' * 100}\nPART 17 — SMALL-ACCOUNT FEASIBILITY (~$1,000 account)\n{'=' * 100}", flush=True)
    entry_prices = [t["entry_price"] for t in primary_trades]
    mean_premium = _mean(entry_prices) if entry_prices else None
    capital_required = mean_premium * CONTRACT_MULTIPLIER if mean_premium else None
    dollar_pnls = [(t["exit_price"] - t["entry_price"]) * CONTRACT_MULTIPLIER for t in primary_trades]
    worst_loss = min(dollar_pnls) if dollar_pnls else None
    expected_pnl = _mean(dollar_pnls) if dollar_pnls else None
    pct_of_account = (capital_required / ACCOUNT_SIZE * 100) if capital_required else None
    print(f"  mean premium=${_fmt(mean_premium)}/share -> capital required per contract=${_fmt(capital_required)}", flush=True)
    print(f"  one contract = {_fmt(pct_of_account)}% of a ${ACCOUNT_SIZE:.0f} account", flush=True)
    print(f"  expected dollar P&L per trade=${_fmt(expected_pnl)}  worst observed loss=${_fmt(worst_loss)}", flush=True)
    positive_returns = [t["return"] for t in primary_trades if t["return"] > 0]
    negative_returns = [t["return"] for t in primary_trades if t["return"] <= 0]
    payoff_ratio = (_mean(positive_returns) / abs(_mean(negative_returns))) if positive_returns and negative_returns and _mean(negative_returns) != 0 else None
    print(f"  payoff ratio (mean win / mean |loss|): {_fmt(payoff_ratio)}", flush=True)
    capital_feasible = capital_required is not None and capital_required <= ACCOUNT_SIZE
    print(f"  CURRENTLY_NOT_CAPITAL_FEASIBLE: {not capital_feasible} (no leverage/margin assumption used)", flush=True)

    # ============================================================== PART 18: POSITION SIZING PROXY (analysis only)
    print(f"\n{'=' * 100}\nPART 18 — POSITION SIZING PROXY (analysis only, no live sizing logic)\n{'=' * 100}", flush=True)
    max_loss_per_contract = abs(worst_loss) if worst_loss is not None and worst_loss < 0 else (capital_required or 0)
    for risk_pct in (0.005, 0.01, 0.02, 0.05):
        risk_budget = ACCOUNT_SIZE * risk_pct
        contracts_affordable_by_risk = int(risk_budget / max_loss_per_contract) if max_loss_per_contract else 0
        print(f"  {risk_pct:.1%} risk budget=${risk_budget:.2f} -> ~{contracts_affordable_by_risk} contract(s) sized to worst observed loss", flush=True)

    # ============================================================== PART 20: PBO/DSR COMPARISON
    print(f"\n{'=' * 100}\nPART 20 — PBO/DSR: P22 ORIGINAL vs P23 TRADEABLE TRANSFORMATION\n{'=' * 100}", flush=True)
    print("  P22 ORIGINAL (discovery-stage IC): PBO=0.700  DSR=0.9991 -- kept in this report, not hidden.", flush=True)
    variant_returns = []
    for threshold in THRESHOLD_GRID:
        t_trades = simulate_trades(by_contract, threshold=threshold, holding_period=PRIMARY["holding_period"], entry_timing=PRIMARY["entry_timing"], first_signal_only=False)
        t_trades_sorted = sorted(t_trades, key=lambda t: t["signal_date"])
        variant_returns.append([t["return"] for t in t_trades_sorted])
    min_len = min((len(v) for v in variant_returns if v), default=0)
    if min_len >= 8:
        n_periods = 6
        bucketed = []
        for v in variant_returns:
            bucket_size = max(1, len(v) // n_periods)
            buckets = [v[i:i + bucket_size] for i in range(0, len(v), bucket_size)][:n_periods]
            bucketed.append([sum(b) / len(b) if b else 0.0 for b in buckets] + [0.0] * (n_periods - len(buckets)))
        pbo = probability_of_backtest_overfitting(bucketed)
        primary_returns_sorted = variant_returns[THRESHOLD_GRID.index(PRIMARY["threshold"])]
        dsr = deflated_sharpe_ratio(primary_returns_sorted, n_trials=len(THRESHOLD_GRID)) if primary_returns_sorted else None
        print(f"  P23 TRADEABLE TRANSFORMATION: {pbo.render()}", flush=True)
        if dsr is not None:
            print(f"  P23 TRADEABLE TRANSFORMATION: DSR: {dsr.render()}", flush=True)
    else:
        print(f"  NOT_APPLICABLE_WITH_REASON: fewer than 8 trades in the shortest threshold variant (min_len={min_len}).", flush=True)

    # ============================================================== PART 21: MULTIPLE TESTING (this family)
    print(f"\n{'#' * 100}\nPART 21 — MULTIPLE-TESTING CORRECTION ({len(raw_p_values)} raw p-values, P23-TRADEABLE family)\n{'#' * 100}", flush=True)
    for method in (bonferroni_correction, holm_bonferroni_correction, benjamini_hochberg_fdr):
        report = method(raw_p_values, alpha=0.05)
        print(f"  {report.method}: n_significant={report.n_significant}/{report.n_tests}", flush=True)

    # ============================================================== FINAL TRADEABLE_SIGNAL_* CLASSIFICATION
    print(f"\n{'#' * 100}\nFINAL TRADEABLE-SIGNAL CLASSIFICATION\n{'#' * 100}", flush=True)
    if every_summary["n"] < 30 or every_summary["mean_return"] is None:
        tradeable_classification = "TRADEABLE_SIGNAL_DATA_INSUFFICIENT"
    elif every_summary["mean_return"] <= 0 or (every_summary["p_value"] or 1.0) >= 0.05:
        tradeable_classification = "TRADEABLE_SIGNAL_REJECTED"
    elif cost_fragile or trade_outlier_dependent or positive_significant_cells < total_cells * 0.5 or (delayed_summary["mean_return"] or 0) <= 0:
        tradeable_classification = "TRADEABLE_SIGNAL_FRAGILE"
    else:
        tradeable_classification = "TRADEABLE_SIGNAL_SUPPORTED"
    print(f"  ==> {tradeable_classification}", flush=True)
    print(f"  CURRENTLY_NOT_CAPITAL_FEASIBLE: {not capital_feasible} (reported separately -- a capital-access fact, not a signal-quality verdict)", flush=True)
    print("  No strategy is created. No order is placed. No parameter was tuned to maximize this grid's P&L.", flush=True)

    exp_store = ExperimentStore(Path("logs/research_data/experiments.jsonl"))
    dims_fp = ExperimentDimensions(
        feature_definition=FEATURE, parameter_range={"threshold_grid": list(THRESHOLD_GRID), "holding_period_grid": list(HOLDING_PERIOD_GRID), "entry_timing_variants": list(ENTRY_TIMING_VARIANTS)},
        universe_name=universe.name, target_definition="next_bar_execution_option_return", execution_model="research-only-next-bar-execution",
        cost_model="assumption-only-1x-2x-3x-5x", validation_methodology="Phase 23 tradeable transformation grid",
    )
    exp_store.record(
        data_version="phase23-panel-v1", feature_version="phase23-tradeable-v1", symbols=list(universe.symbols), timeframe="day",
        strategy_version="1.0", prediction_horizon=PRIMARY["holding_period"], train_period=("2021-12-01", "2023-06-15"),
        parameters={"primary": PRIMARY, "n_raw_p_values": len(raw_p_values)}, metrics={"primary_mean_return": every_summary["mean_return"] or 0.0, "primary_n_trades": every_summary["n"]},
        strategy_family="p23_opt_013_tradeable", classification=tradeable_classification,
        tags=("phase23-tradeable", universe.name, "mark-to-market-historical-research", "research-only-no-orders"),
        notes=f"capital_feasible={capital_feasible}", hypothesis_id=INV_ID, universe_name=universe.name,
        experiment_fingerprint=compute_experiment_fingerprint(dims_fp), research_family_id="P23-TRADEABLE-2026-09",
    )
    print("\nSTEP 4 COMPLETE.", flush=True)


if __name__ == "__main__":
    main()
