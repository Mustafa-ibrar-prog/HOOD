#!/usr/bin/env python3
"""Walk-forward backtest + training for the BTC direction model
(btc_direction_model.py) -- builds a labeled historical dataset
(btc_training_data.py), evaluates it chronologically (never shuffled),
and reports the honest metrics this round's requirements specify:
accuracy, precision/recall by side, Brier score, calibration,
average edge, trade frequency, simulated P&L (fees/slippage/TP/SL),
max drawdown, win rate, avg win/loss, profit factor.

====================================================================
READ THIS BEFORE TRUSTING ANY NUMBER THIS SCRIPT PRINTS
====================================================================

Data source, in priority order:
  1. --bars-file: a JSON file of real OHLCV bars you supply (same
     shape BtcPriceHistoryStore.save_real_bars() writes). Use this
     once you have a genuine historical Coinbase (or similar) BTC
     candle dump, pulled from an environment with real network
     access -- this sandboxed session has NONE (outbound HTTPS to
     Coinbase/Polymarket is denied by this environment's network
     policy; confirmed directly, not assumed).
  2. --price-history-file: BtcPriceHistoryStore's own accumulated
     real-bar file (bars.json next to whatever POLYMARKET_BTC_PRICE_HISTORY_FILE
     points at) -- genuinely real Coinbase data, but only as much as
     this bot has actually been running to collect. Likely far too
     little for a statistically meaningful backtest early on.
  3. --synthetic N: a labeled-SYNTHETIC geometric-random-walk price
     series (btc_training_data.generate_synthetic_bars) -- used ONLY
     to prove this harness (feature computation, walk-forward
     splitting, model fitting, metric computation, P&L simulation)
     runs correctly end to end, with no look-ahead bugs. A random
     walk has no real exploitable structure; any "accuracy" or "P&L"
     number this produces reflects the synthetic series' own
     incidental, essentially coin-flip structure, NOT a genuine
     edge over real BTC markets. Every report this mode produces
     says SYNTHETIC in bold at the top and in the saved JSON.

THIS SCRIPT NEVER PLACES A LIVE ORDER. It only reads/writes local
files (the dataset it built, the trained model, this report).

A model trained here is written to --output-model. engine.py (via
run_cycle()'s own model parameter, loaded in
scripts/run_polymarket_bot.py from POLYMARKET_MODEL_WEIGHTS_FILE) will
use it VERBATIM once pointed at it -- there is no additional gate here
preventing a demo/synthetic model from being wired into live trading
BESIDES this report's own explicit warning. Read the data_source field
of the saved model file before ever pointing production at it.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.market.models import PriceBar  # noqa: E402
from src.polymarket.btc_direction_model import BtcDirectionModel  # noqa: E402
from src.polymarket.btc_market_data import BtcPriceHistoryStore  # noqa: E402
from src.polymarket.btc_training_data import (  # noqa: E402
    TrainingExample,
    build_training_dataset,
    generate_synthetic_bars,
    walk_forward_folds,
)

TAKE_PROFIT_PCT = 0.10
STOP_LOSS_PCT = 0.20
ENTRY_SIZE_USD = 20.0


def _load_bars_file(path: Path) -> list[PriceBar]:
    raw = json.loads(path.read_text())
    bars = []
    for row in raw:
        from datetime import datetime
        bars.append(PriceBar(
            start_time=datetime.fromisoformat(row["start_time"]), open=float(row["open"]), high=float(row["high"]),
            low=float(row["low"]), close=float(row["close"]), volume=float(row.get("volume", 0.0)),
        ))
    return sorted(bars, key=lambda b: b.start_time)


def _brier_score(predictions: list[float], labels: list[int]) -> float:
    return sum((p - y) ** 2 for p, y in zip(predictions, labels)) / len(predictions)


def _calibration_bins(predictions: list[float], labels: list[int], *, n_bins: int = 10) -> list[dict]:
    bins = [[] for _ in range(n_bins)]
    for p, y in zip(predictions, labels):
        idx = min(n_bins - 1, int(p * n_bins))
        bins[idx].append((p, y))
    report = []
    for i, bucket in enumerate(bins):
        if not bucket:
            continue
        mean_predicted = sum(p for p, _ in bucket) / len(bucket)
        actual_rate = sum(y for _, y in bucket) / len(bucket)
        report.append({
            "bin": f"{i / n_bins:.1f}-{(i + 1) / n_bins:.1f}", "n": len(bucket),
            "mean_predicted": round(mean_predicted, 4), "actual_up_rate": round(actual_rate, 4),
        })
    return report


def _breakdown_by_time_remaining(examples: list[TrainingExample], predictions: list[float], labels: list[int]) -> list[dict]:
    """Performance by time remaining -- explicitly requested, and
    important for honesty: a checkpoint seconds before a window
    closes has a current_price already very close to the final
    settlement price, so accuracy there is expected to be high almost
    by construction (the price has mostly stopped moving), not
    because the model has "figured out" anything far in advance. A
    checkpoint far from close (e.g. 840s remaining) is the genuinely
    hard, useful case."""
    buckets: dict[int, list[tuple[float, int]]] = {}
    for example, p, y in zip(examples, predictions, labels):
        seconds_remaining = round(example.features.time_remaining_seconds or 0.0)
        buckets.setdefault(seconds_remaining, []).append((p, y))
    report = []
    for seconds_remaining in sorted(buckets, reverse=True):
        bucket = buckets[seconds_remaining]
        correct = sum(1 for p, y in bucket if (1 if p >= 0.5 else 0) == y)
        report.append({
            "seconds_remaining": seconds_remaining, "n": len(bucket), "accuracy": round(correct / len(bucket), 4),
            "brier_score": round(_brier_score([p for p, _ in bucket], [y for _, y in bucket]), 4),
        })
    return report


def _breakdown_by_distance_from_price_to_beat(examples: list[TrainingExample], predictions: list[float], labels: list[int]) -> list[dict]:
    """Performance by |distance from price-to-beat|, as a percentage
    -- explicitly requested. A wide distance (the price has already
    moved well away from price-to-beat) should be easy to call
    correctly; a near-zero distance is the genuinely uncertain,
    coin-flip-adjacent case."""
    buckets_pct = [0.0, 0.0005, 0.001, 0.002, 0.005, float("inf")]
    bucketed: list[list[tuple[float, int]]] = [[] for _ in range(len(buckets_pct) - 1)]
    for example, p, y in zip(examples, predictions, labels):
        pct = abs(example.features.distance_from_price_to_beat_pct or 0.0)
        for i in range(len(buckets_pct) - 1):
            if buckets_pct[i] <= pct < buckets_pct[i + 1]:
                bucketed[i].append((p, y))
                break
    report = []
    for i, bucket in enumerate(bucketed):
        if not bucket:
            continue
        correct = sum(1 for p, y in bucket if (1 if p >= 0.5 else 0) == y)
        label = f"{buckets_pct[i] * 100:.2f}%-{buckets_pct[i + 1] * 100:.2f}%" if buckets_pct[i + 1] != float("inf") else f">={buckets_pct[i] * 100:.2f}%"
        report.append({"abs_distance_pct_bucket": label, "n": len(bucket), "accuracy": round(correct / len(bucket), 4)})
    return report


def _simulate_trade_pnl(*, entry_price: float, favored_up: bool, example: TrainingExample) -> float:
    """Deterministic, no-lookahead-safe P&L simulation for ONE
    simulated trade on ONE historical window, using ONLY that
    window's own already-known final outcome (never a resolved value
    the model couldn't have seen at decision time -- the ENTRY
    decision itself only ever used features computed strictly before
    the checkpoint; this function just resolves what WOULD have
    happened to a position opened at that checkpoint, using the
    window's real, already-realized final label). Mirrors
    take_profit.py's real TP/SL rule applied to the single, final
    settlement price (this backtest has no intra-window bid/ask path,
    so it can only ever check settlement -- a real backtest with
    genuine tick-level Polymarket order-book history could check
    TP/SL hits intra-window too; this script is honest that it does
    not have that data)."""
    shares = ENTRY_SIZE_USD / entry_price
    settlement_price = 1.0 if favored_up == (example.label == 1) else 0.0
    target_price = entry_price * (1 + TAKE_PROFIT_PCT)
    stop_price = entry_price * (1 - STOP_LOSS_PCT)
    if settlement_price >= target_price:
        exit_price = target_price
    elif settlement_price <= stop_price:
        exit_price = stop_price
    else:
        exit_price = settlement_price
    return shares * exit_price - ENTRY_SIZE_USD


def evaluate_fold(model: BtcDirectionModel, test: list[TrainingExample], *, min_edge: float, fee_pct: float, slippage_pct: float) -> dict:
    predictions = []
    labels = []
    edges = []
    trades = []
    for example in test:
        up_proba = model.predict_proba(example.features.as_feature_dict())
        predictions.append(up_proba)
        labels.append(example.label)
        # This backtest has no real historical Polymarket order-book
        # data (see module docstring) -- the market price is modeled
        # as the window's own realized outcome probability baseline
        # (0.5, an uninformed market) plus nothing else, so "edge"
        # here is reported against a neutral market prior ONLY for
        # diagnostic purposes (average_edge_vs_neutral_market below);
        # it is NOT comparable to btc_model_entry_signal.py's real,
        # live-order-book-based edge calculation.
        market_up_proxy = 0.5
        up_edge = up_proba - market_up_proxy
        down_edge = (1 - up_proba) - market_up_proxy
        edges.append(max(up_edge, down_edge))
        favored_up = up_proba >= 0.5
        edge = up_edge if favored_up else down_edge
        if edge - fee_pct - slippage_pct >= min_edge:
            # Neutral market proxy (0.5) on EITHER side, symmetric,
            # since no real historical order-book price exists here.
            pnl = _simulate_trade_pnl(entry_price=market_up_proxy, favored_up=favored_up, example=example)
            trades.append(pnl)

    predicted_labels = [1 if p >= 0.5 else 0 for p in predictions]
    n = len(test)
    correct = sum(1 for p, y in zip(predicted_labels, labels) if p == y)
    up_predicted = [(p, y) for p, y in zip(predicted_labels, labels) if p == 1]
    down_predicted = [(p, y) for p, y in zip(predicted_labels, labels) if p == 0]
    up_actual = sum(1 for y in labels if y == 1)
    down_actual = sum(1 for y in labels if y == 0)

    precision_up = (sum(1 for _, y in up_predicted if y == 1) / len(up_predicted)) if up_predicted else None
    recall_up = (sum(1 for p, y in zip(predicted_labels, labels) if p == 1 and y == 1) / up_actual) if up_actual else None
    precision_down = (sum(1 for _, y in down_predicted if y == 0) / len(down_predicted)) if down_predicted else None
    recall_down = (sum(1 for p, y in zip(predicted_labels, labels) if p == 0 and y == 0) / down_actual) if down_actual else None

    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    equity_curve = []
    running = 0.0
    for t in trades:
        running += t
        equity_curve.append(running)
    peak = float("-inf")
    max_drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, peak - value)

    return {
        "n_examples": n,
        "accuracy": round(correct / n, 4) if n else None,
        "precision_up": round(precision_up, 4) if precision_up is not None else None,
        "recall_up": round(recall_up, 4) if recall_up is not None else None,
        "precision_down": round(precision_down, 4) if precision_down is not None else None,
        "recall_down": round(recall_down, 4) if recall_down is not None else None,
        "brier_score": round(_brier_score(predictions, labels), 4),
        "calibration": _calibration_bins(predictions, labels),
        "average_edge_vs_neutral_market": round(sum(edges) / len(edges), 4) if edges else None,
        "trade_frequency": round(len(trades) / n, 4) if n else None,
        "n_trades": len(trades),
        "simulated_pnl_total": round(sum(trades), 2),
        "win_rate": round(len(wins) / len(trades), 4) if trades else None,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 4) if losses and sum(losses) != 0 else None,
        "max_drawdown": round(max_drawdown, 2),
        "performance_by_time_remaining": _breakdown_by_time_remaining(test, predictions, labels),
        "performance_by_distance_from_price_to_beat": _breakdown_by_distance_from_price_to_beat(test, predictions, labels),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bars-file", type=Path, default=None, help="Real historical OHLCV bars (JSON)")
    parser.add_argument("--price-history-file", type=Path, default=None, help="BtcPriceHistoryStore's own accumulated bars file")
    parser.add_argument("--synthetic", type=int, default=None, metavar="N", help="Generate N synthetic 1-minute bars instead (pipeline validation ONLY)")
    parser.add_argument("--synthetic-seed", type=int, default=0)
    parser.add_argument("--n-folds", type=int, default=5)
    parser.add_argument("--min-edge", type=float, default=0.05)
    parser.add_argument("--fee-pct", type=float, default=0.0)
    parser.add_argument("--slippage-pct", type=float, default=0.01)
    parser.add_argument("--output-model", type=Path, default=Path("logs/polymarket/btc_direction_model.json"))
    parser.add_argument("--output-report", type=Path, default=Path("logs/polymarket/backtest_report.json"))
    args = parser.parse_args()

    if args.bars_file:
        bars = _load_bars_file(args.bars_file)
        data_source = "real"
        print(f"Loaded {len(bars)} REAL bars from {args.bars_file}")
    elif args.price_history_file:
        bars = BtcPriceHistoryStore(args.price_history_file).load_real_bars()
        bars = sorted(bars, key=lambda b: b.start_time)
        data_source = "real"
        print(f"Loaded {len(bars)} REAL bars accumulated in {args.price_history_file}")
    elif args.synthetic:
        bars = generate_synthetic_bars(num_bars=args.synthetic, seed=args.synthetic_seed)
        data_source = "synthetic"
        print(
            f"\n{'=' * 70}\nSYNTHETIC DATA MODE -- generated {args.synthetic} bars (seed={args.synthetic_seed}).\n"
            "This is a geometric random walk, NOT real BTC market history.\n"
            "Every metric below exercises this harness's own correctness\n"
            "(no look-ahead, walk-forward splitting, metric computation) --\n"
            "it proves NOTHING about whether this model would make money on\n"
            "real BTC markets. Do not use this to justify live trading.\n" + "=" * 70 + "\n"
        )
    else:
        print("ERROR: one of --bars-file / --price-history-file / --synthetic is required.", file=sys.stderr)
        return 2

    if len(bars) < 32:
        print(f"ERROR: only {len(bars)} bars available -- need at least 32 (one full window + lead-in) to build any training example.", file=sys.stderr)
        return 2

    examples = build_training_dataset(bars, data_source=data_source)
    print(f"Built {len(examples)} training examples from {len(bars)} bars "
          f"({sum(1 for e in examples if e.label == 1)} UP / {sum(1 for e in examples if e.label == 0)} DOWN).")

    if not examples:
        print("ERROR: zero training examples -- not enough history for even one complete, labeled 15-minute window.", file=sys.stderr)
        return 2

    folds = walk_forward_folds(examples, n_folds=args.n_folds, min_train_examples=max(10, len(examples) // (args.n_folds * 4)))
    if not folds:
        print("ERROR: not enough examples to form any walk-forward fold with a non-trivial training set.", file=sys.stderr)
        return 2

    print(f"\n--- WALK-FORWARD EVALUATION ({len(folds)} fold(s), chronological, never shuffled) ---")
    fold_reports = []
    for i, (train, test) in enumerate(folds):
        model = BtcDirectionModel.fit(
            [(e.features.as_feature_dict(), e.label) for e in train], epochs=300, data_source=data_source,
        )
        report = evaluate_fold(model, test, min_edge=args.min_edge, fee_pct=args.fee_pct, slippage_pct=args.slippage_pct)
        report["fold"] = i
        report["train_size"] = len(train)
        fold_reports.append(report)
        print(
            f"fold {i}: train={len(train)} test={len(test)} accuracy={report['accuracy']} "
            f"brier={report['brier_score']} n_trades={report['n_trades']} pnl=${report['simulated_pnl_total']} "
            f"win_rate={report['win_rate']} max_drawdown=${report['max_drawdown']}"
        )

    overall_pnl = sum(r["simulated_pnl_total"] for r in fold_reports)
    overall_trades = sum(r["n_trades"] for r in fold_reports)
    overall_accuracy = sum(r["accuracy"] * r["n_examples"] for r in fold_reports) / sum(r["n_examples"] for r in fold_reports)

    print(f"\n--- SUMMARY ACROSS ALL FOLDS ---")
    print(f"data_source={data_source}")
    print(f"total test examples: {sum(r['n_examples'] for r in fold_reports)}")
    print(f"weighted accuracy: {overall_accuracy:.4f}")
    print(f"total simulated trades: {overall_trades}")
    print(f"total simulated P&L: ${overall_pnl:.2f}")

    print("\n--- PERFORMANCE BY TIME REMAINING (last fold; near-close checkpoints are expected to")
    print("    be much easier -- the price has mostly already settled by then) ---")
    for row in fold_reports[-1]["performance_by_time_remaining"]:
        print(f"  {row['seconds_remaining']:>5}s remaining: n={row['n']:>5} accuracy={row['accuracy']} brier={row['brier_score']}")

    print("\n--- PERFORMANCE BY |DISTANCE FROM PRICE-TO-BEAT| (last fold) ---")
    for row in fold_reports[-1]["performance_by_distance_from_price_to_beat"]:
        print(f"  {row['abs_distance_pct_bucket']:>14}: n={row['n']:>5} accuracy={row['accuracy']}")

    if data_source == "synthetic":
        print("\n*** REMINDER: data_source=synthetic. The P&L/accuracy above is a pipeline-correctness ***")
        print("*** check, not a real backtest. Do not conclude this model is profitable.              ***")

    # Final production model: trained on ALL available data.
    final_model = BtcDirectionModel.fit(
        [(e.features.as_feature_dict(), e.label) for e in examples], epochs=500, data_source=data_source,
    )
    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    final_model.save(args.output_model)
    print(f"\nFinal model (trained on all {len(examples)} examples, data_source={data_source}) saved to {args.output_model}")

    report = {
        "data_source": data_source, "n_bars": len(bars), "n_examples": len(examples), "n_folds": len(folds),
        "fold_reports": fold_reports, "overall_weighted_accuracy": round(overall_accuracy, 4),
        "overall_simulated_pnl": round(overall_pnl, 2), "overall_n_trades": overall_trades,
        "min_edge": args.min_edge, "fee_pct": args.fee_pct, "slippage_pct": args.slippage_pct,
        "warning": (
            "data_source=synthetic: this report validates the backtest HARNESS only, not real "
            "predictive performance -- see this script's own module docstring." if data_source == "synthetic" else
            "data_source=real, but verify n_bars/n_examples are large enough for statistical significance "
            "before trusting these numbers for live trading."
        ),
    }
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(json.dumps(report, indent=2, default=str))
    print(f"Full report saved to {args.output_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
