#!/usr/bin/env python3
"""Phase 7 — STEP 5: demonstrates purged/embargoed CV on REAL market data
(the same US_DIVERSIFIED panel the discovery campaign used), complementing
the synthetic-data proof in tests/test_purged_cv.py. Shows, concretely,
how many training samples a naive K-fold would have leaked on this
exact dataset for a 5-bar-ahead target, and confirms the purged version
eliminates that leakage entirely. Read-only — no backtest, no orders.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import HistoricalDataStore, us_diversified_universe  # noqa: E402
from src.research.purged_cv import PurgedCVConfig, fold_has_leakage, generate_purged_folds  # noqa: E402


class _FakeFold:
    def __init__(self, test_indices, train_indices):
        self.test_indices = tuple(test_indices)
        self.train_indices = tuple(train_indices)


def naive_kfold_bounds(n: int, k: int) -> list[tuple[int, int]]:
    base, rem = divmod(n, k)
    bounds, start = [], 0
    for i in range(k):
        size = base + (1 if i < rem else 0)
        bounds.append((start, start + size))
        start += size
    return bounds


def main() -> None:
    store = HistoricalDataStore(Path("logs/research_data"))
    universe = us_diversified_universe()
    bars = store.load("AAPL", "day")  # one representative symbol's real timestamp series
    timestamps = [b.timestamp for b in bars]
    print(f"Real timestamps: {len(timestamps)} bars, {timestamps[0].date()} .. {timestamps[-1].date()}", flush=True)

    horizon = 5  # matches most Phase 7 discovery hypotheses' prediction_horizon_bars
    config = PurgedCVConfig(n_splits=6, prediction_horizon_bars=horizon, purge_window_bars=1, embargo_bars=5)
    purged_folds = generate_purged_folds(timestamps, config)

    print(f"\nPURGED CV ({config.n_splits} folds, horizon={horizon} bars, purge={config.purge_window_bars}, embargo={config.embargo_bars}):", flush=True)
    purged_leaks = 0
    for f in purged_folds:
        leaked = fold_has_leakage(f, timestamps, prediction_horizon_bars=horizon)
        purged_leaks += leaked
        print(f"  fold {f.fold_index}: test_n={len(f.test_indices)} train_n={len(f.train_indices)} purged={f.purged_count} embargoed={f.embargoed_count} LEAKED={leaked}", flush=True)

    print(f"\nNAIVE (non-purged) K-fold on the SAME real dataset:", flush=True)
    naive_leaks = 0
    naive_leaked_train_samples = 0
    for test_start, test_end in naive_kfold_bounds(len(timestamps), config.n_splits):
        train_idx = [i for i in range(len(timestamps)) if i < test_start or i >= test_end]
        fake = _FakeFold(range(test_start, test_end), train_idx)
        leaked = fold_has_leakage(fake, timestamps, prediction_horizon_bars=horizon)
        naive_leaks += leaked
        if leaked:
            leaked_count = sum(
                1 for i in train_idx
                if not (timestamps[i] + horizon * (timestamps[1] - timestamps[0]) < timestamps[test_start] or timestamps[i] > timestamps[test_end - 1])
            )
            naive_leaked_train_samples += leaked_count
        print(f"  fold: test_n={test_end - test_start} train_n={len(train_idx)} LEAKED={leaked}", flush=True)

    print(f"\nRESULT: naive K-fold leaked in {naive_leaks}/{config.n_splits} folds on real data "
          f"(~{naive_leaked_train_samples} training samples with label-window overlap into a test fold). "
          f"Purged CV leaked in {purged_leaks}/{config.n_splits} folds.", flush=True)


if __name__ == "__main__":
    main()
