"""Builds a labeled historical dataset for the BTC direction model
(see btc_direction_model.py) from a chronological sequence of 1-minute
BTC bars -- one TrainingExample per (historical 15-minute window,
evaluation checkpoint) pair, using ONLY btc_features.compute_btc_features()
(the SAME function production/paper trading calls), so a training row
and a live decision are computed identically -- never a second,
independently-written feature pipeline that could silently drift from
what actually runs live.

WALK-FORWARD, NEVER SHUFFLED: build_training_dataset() preserves the
chronological order its input bars arrive in; callers (see
scripts/backtest_btc_direction_model.py) are responsible for slicing
TRAIN/TEST splits by TIME (train on examples whose window starts
before a cutoff, test strictly after), never by a random shuffle --
shuffling here would let a later window's outcome leak into an
earlier window's training fold through nothing but bad luck in which
rows land on which side.

HONEST DATA SOURCING: build_training_dataset() takes whatever bars
it's given -- it does not fetch anything itself. Two real sources this
module supports:
  - load_bars_from_price_history_store(): the SAME file real/paper
    live trading has been accumulating in BtcPriceHistoryStore
    (bars.json) -- genuinely real Coinbase data, but only as much as
    this bot has actually been running to collect.
  - generate_synthetic_bars(): a labeled-SYNTHETIC random-walk BTC
    price series, for exercising/validating this ENTIRE pipeline
    (feature computation, walk-forward splitting, model fitting,
    backtest metrics) end to end when no real historical dataset is
    available yet -- e.g. this session has no outbound network access
    to pull real historical Coinbase/Polymarket data (see the backtest
    script's own report for why). Every example built from it is
    stamped TrainingExample.data_source="synthetic" so a result built
    from it can never be mistaken for a genuine historical backtest.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.market.models import PriceBar
from src.polymarket.btc_features import compute_btc_features
from src.polymarket.btc_market_data import BtcPriceHistoryStore

WINDOW_SECONDS = 15 * 60

# Checkpoints within each 15-minute window, expressed as seconds
# REMAINING at evaluation time -- deliberately sparse (one training
# row per checkpoint per window, not every possible second) so the
# dataset isn't dominated by near-duplicate adjacent-second rows from
# the same window. Mirrors how often a live bot (10s poll_interval_seconds
# default) would actually get a fresh look, without the dataset
# growing by a row-per-second factor.
DEFAULT_CHECKPOINTS_SECONDS_REMAINING: tuple[int, ...] = (840, 600, 420, 240, 120, 60, 30, 10)


@dataclass(frozen=True)
class TrainingExample:
    features: BtcFeatureVector
    label: int  # 1 == UP (close_price > price_to_beat), 0 == DOWN
    window_start: datetime
    window_end: datetime
    data_source: str  # "real" | "synthetic" -- see module docstring


def load_bars_from_price_history_store(store: BtcPriceHistoryStore) -> list[PriceBar]:
    """Real bars this bot has actually accumulated (see
    btc_market_data.BtcPriceHistoryStore) -- sorted oldest first. Never
    fetches anything itself; whatever is in the store's file is what
    you get, which may be far too little history for a meaningful
    backtest if the bot hasn't been running long (see the backtest
    script's own reporting of how much it had to work with)."""
    return sorted(store.load_real_bars(), key=lambda b: b.start_time)


def generate_synthetic_bars(
    *, num_bars: int, start: datetime | None = None, seed: int = 0, starting_price: float = 65_000.0,
    minute_vol_pct: float = 0.0008,
) -> list[PriceBar]:
    """A labeled-SYNTHETIC geometric-random-walk 1-minute BTC price
    series -- for pipeline validation only (see module docstring). NOT
    real BTC market history; every TrainingExample built from this is
    stamped data_source="synthetic". Deterministic given `seed`, so a
    backtest run against it is reproducible."""
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    rng = random.Random(seed)
    bars: list[PriceBar] = []
    price = starting_price
    for i in range(num_bars):
        drift = rng.gauss(0.0, minute_vol_pct)
        open_price = price
        price = max(1.0, price * (1.0 + drift))
        high = max(open_price, price) * (1.0 + abs(rng.gauss(0.0, minute_vol_pct / 4)))
        low = min(open_price, price) * (1.0 - abs(rng.gauss(0.0, minute_vol_pct / 4)))
        volume = max(0.0, rng.gauss(50.0, 15.0))
        bars.append(PriceBar(
            start_time=start + timedelta(minutes=i), open=open_price, high=high, low=low, close=price,
            volume=volume,
        ))
    return bars


def build_training_dataset(
    bars: list[PriceBar], *, data_source: str, checkpoints_seconds_remaining: tuple[int, ...] = DEFAULT_CHECKPOINTS_SECONDS_REMAINING,
) -> list[TrainingExample]:
    """Slices `bars` (must be 1-minute, chronological, gapless enough
    to form 15-minute windows -- a gap just means fewer complete
    windows, never an error) into NON-OVERLAPPING, chronological
    15-minute windows. For each window: price_to_beat = the window's
    own opening bar's `open` (the exact proxy-definition
    btc_features.resolve_price_to_beat() uses live, applied here
    directly since backtest bars already cover window_start exactly);
    label = 1 (UP) if the window's closing bar's `close` >
    price_to_beat, 0 (DOWN) if strictly less. A window whose close
    price EXACTLY equals price_to_beat is EXCLUDED (a push -- real
    BTC Up/Down contracts do not resolve a tie into either side, and
    labeling it either way would poison the model with a fabricated
    outcome). For each checkpoint, computes the feature vector using
    ONLY bars strictly before that checkpoint's timestamp (see
    btc_features.compute_btc_features's own NO LOOK-AHEAD guarantee) --
    never the window's own future bars."""
    bars = sorted(bars, key=lambda b: b.start_time)
    examples: list[TrainingExample] = []
    if len(bars) < 16:
        return examples

    by_start = {b.start_time: b for b in bars}
    i = 0
    while i + 15 < len(bars):
        window_bars = bars[i:i + 16]
        window_start = window_bars[0].start_time
        window_end = window_start + timedelta(seconds=WINDOW_SECONDS)
        if window_bars[-1].start_time != window_start + timedelta(minutes=15):
            i += 1
            continue  # a gap in the data -- skip one bar forward rather than silently stretching the window

        price_to_beat = window_bars[0].open
        close_price = window_bars[-1].open  # the bar AT window_end hasn't happened yet -- its own open is the price AT that instant
        if close_price == price_to_beat:
            i += 16
            continue  # push -- excluded, never labeled either way

        label = 1 if close_price > price_to_beat else 0

        history_cutoff_bars = [b for b in bars if b.start_time < window_start]
        for seconds_remaining in checkpoints_seconds_remaining:
            at = window_end - timedelta(seconds=seconds_remaining)
            visible_bars = history_cutoff_bars + [b for b in window_bars if b.start_time < at]
            vector = compute_btc_features(visible_bars, at=at, price_to_beat=price_to_beat, close_time=window_end)
            if not vector.has_minimum_data:
                continue
            examples.append(TrainingExample(
                features=vector, label=label, window_start=window_start, window_end=window_end,
                data_source=data_source,
            ))
        i += 16
    return examples


def walk_forward_folds(
    examples: list[TrainingExample], *, n_folds: int, min_train_examples: int = 50,
) -> list[tuple[list[TrainingExample], list[TrainingExample]]]:
    """Chronological expanding-window walk-forward: fold k trains on
    every example whose window_start is before fold k's test block
    and tests on that block, for `n_folds` equal-sized, TIME-ORDERED
    blocks of the (already chronological) `examples` list -- never a
    random split. A fold is skipped (not yielded) if it would have
    fewer than `min_train_examples` in its training set, since an
    almost-empty training fold produces a meaningless model, not a
    meaningfully bad one."""
    examples = sorted(examples, key=lambda e: e.window_start)
    n = len(examples)
    if n_folds <= 0 or n == 0:
        return []
    fold_size = max(1, n // n_folds)
    folds: list[tuple[list[TrainingExample], list[TrainingExample]]] = []
    for fold_index in range(n_folds):
        test_start = fold_index * fold_size
        test_end = n if fold_index == n_folds - 1 else min(n, test_start + fold_size)
        if test_start >= n:
            break
        train = examples[:test_start]
        test = examples[test_start:test_end]
        if len(train) < min_train_examples or not test:
            continue
        folds.append((train, test))
    return folds
