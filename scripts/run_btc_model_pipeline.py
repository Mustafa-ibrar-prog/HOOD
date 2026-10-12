#!/usr/bin/env python3
"""ONE command for the entire BTC direction model pipeline: raw data ->
dataset -> training -> backtest. Chains two existing, independently
testable/runnable scripts together -- this file adds NO new modeling
logic of its own, it only orchestrates:

    1. scripts/download_btc_historical_bars.py -- downloads real
       historical BTC 1-minute OHLCV from Coinbase and saves it to
       --bars-file (skip with --skip-download if you already have a
       bars file you trust and just want to re-train/re-backtest).
    2. scripts/backtest_btc_direction_model.py --bars-file <same file>
       -- builds the causal 15-minute training dataset
       (btc_training_data.py), trains btc_direction_model.py
       chronologically per walk-forward fold (never shuffled), saves
       the final model to --output-model, and writes the full metrics
       report to --output-report.

THIS SCRIPT NEVER PLACES A POLYMARKET ORDER -- neither step it runs
does either (download is read-only HTTPS to Coinbase; the backtest
only reads/writes local files).

Usage (run on a machine with real network access -- see this round's
PowerShell command list for the exact invocation):

    python3 scripts/run_btc_model_pipeline.py \\
        --start 2026-07-01 --end 2026-10-01 \\
        --bars-file logs/polymarket/btc_historical_bars.json \\
        --output-model logs/polymarket/btc_direction_model.json

Then point POLYMARKET_MODEL_WEIGHTS_FILE at --output-model and run
scripts/run_paper_trading.py to validate against LIVE data before ever
considering live trading.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_DOWNLOAD_SCRIPT = _SCRIPTS_DIR / "download_btc_historical_bars.py"
_BACKTEST_SCRIPT = _SCRIPTS_DIR / "backtest_btc_direction_model.py"


def _run_step(label: str, argv: list[str]) -> int:
    print(f"\n{'=' * 70}\nSTEP: {label}\n{'=' * 70}")
    print(f"$ {' '.join(argv)}")
    result = subprocess.run(argv)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default=None, help="Download start (required unless --skip-download), e.g. 2026-07-01")
    parser.add_argument("--end", default=None, help="Download end (default: now)")
    parser.add_argument("--product-id", default="BTC-USD")
    parser.add_argument("--bars-file", type=Path, default=Path("logs/polymarket/btc_historical_bars.json"))
    parser.add_argument("--request-delay-seconds", type=float, default=None)
    parser.add_argument("--skip-download", action="store_true", help="Skip step 1 -- train/backtest directly against the bars already at --bars-file")
    parser.add_argument("--n-folds", type=int, default=5)
    parser.add_argument("--min-edge", type=float, default=0.05)
    parser.add_argument("--fee-pct", type=float, default=0.0)
    parser.add_argument("--slippage-pct", type=float, default=0.01)
    parser.add_argument("--output-model", type=Path, default=Path("logs/polymarket/btc_direction_model.json"))
    parser.add_argument("--output-report", type=Path, default=Path("logs/polymarket/backtest_report.json"))
    args = parser.parse_args()

    if not args.skip_download:
        if not args.start:
            print("ERROR: --start is required unless --skip-download is given.", file=sys.stderr)
            return 2
        download_argv = [
            sys.executable, str(_DOWNLOAD_SCRIPT),
            "--start", args.start, "--product-id", args.product_id, "--output", str(args.bars_file),
        ]
        if args.end:
            download_argv += ["--end", args.end]
        if args.request_delay_seconds is not None:
            download_argv += ["--request-delay-seconds", str(args.request_delay_seconds)]
        rc = _run_step("1/2 download real historical BTC bars", download_argv)
        if rc != 0:
            print(f"\nPipeline stopped: download step exited {rc}.", file=sys.stderr)
            return rc
    else:
        print(f"\n--skip-download: using whatever is already saved at {args.bars_file}")
        if not args.bars_file.is_file():
            print(f"ERROR: --skip-download was given but {args.bars_file} does not exist.", file=sys.stderr)
            return 2

    backtest_argv = [
        sys.executable, str(_BACKTEST_SCRIPT),
        "--bars-file", str(args.bars_file), "--n-folds", str(args.n_folds), "--min-edge", str(args.min_edge),
        "--fee-pct", str(args.fee_pct), "--slippage-pct", str(args.slippage_pct),
        "--output-model", str(args.output_model), "--output-report", str(args.output_report),
    ]
    rc = _run_step("2/2 build dataset, train (walk-forward), backtest", backtest_argv)
    if rc != 0:
        print(f"\nPipeline stopped: backtest/training step exited {rc}.", file=sys.stderr)
        return rc

    print(
        f"\n{'=' * 70}\nPIPELINE COMPLETE\n{'=' * 70}\n"
        f"Trained model: {args.output_model}\n"
        f"Full report:   {args.output_report}\n"
        f"To use this model: set POLYMARKET_MODEL_WEIGHTS_FILE={args.output_model} in your .env, "
        "then run scripts/run_paper_trading.py (never live) to validate against live data first."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
