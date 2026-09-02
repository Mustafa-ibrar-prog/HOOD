"""Phase 11, Part 27: block/stationary bootstrap ON A PERIOD-RETURN
SERIES, not on discrete trades.

src.research.placebo's block_bootstrap_trade_statistics /
stationary_bootstrap_trade_statistics (Phase 7, unmodified) resample
DISCRETE TRADE P&Ls — the right unit of analysis for a strategy that
enters and exits distinct positions. A volatility-CONDITIONED-EXPOSURE
strategy is fundamentally different: it continuously rebalances a single
ongoing allocation, so its "trades" are rebalance-driven buy/sell
fragments whose individual P&L is not economically meaningful in
isolation (a single rebalance day might generate a trade of $40 from a
5% exposure trim). The correct object to bootstrap for THIS kind of
strategy is its own PERIOD (e.g. daily) RETURN SERIES — the standard
approach for evaluating a continuous allocation's Sharpe-ratio stability.

Reuses placebo.py's own `_bootstrap_report_from_resamples` for the actual
CI construction (identical statistical machinery, only the resampling
UNIT changes from trade-P&L to period-return) — genuine reuse, not a
parallel reimplementation of the confidence-interval math.
"""

from __future__ import annotations

import random
from typing import Sequence

from src.research.analysis import mean, stdev
from src.research.placebo import MIN_BOOTSTRAP_SAMPLE, BootstrapReport, _bootstrap_report_from_resamples


def block_bootstrap_return_series(returns: Sequence[float], *, block_size: int, n_resamples: int = 2000, seed: int = 42, confidence_level: float = 0.90) -> BootstrapReport:
    """Moving block bootstrap on a period-return series — see
    placebo.block_bootstrap_trade_statistics's docstring for the general
    method; identical mechanics, applied to returns instead of trade P&L."""
    if block_size < 1:
        raise ValueError("block_size must be >= 1")
    n = len(returns)
    if n < MIN_BOOTSTRAP_SAMPLE:
        return BootstrapReport(sample_size=n, insufficient_sample=True, mean_trade_return_ci=None, expectancy_ci=None, cumulative_return_ci=None, sharpe_like_ci=None)
    if block_size > n:
        raise ValueError(f"block_size ({block_size}) cannot exceed the number of observations ({n})")

    rng = random.Random(seed)
    n_blocks_needed = -(-n // block_size)
    means: list[float] = []
    cumulatives: list[float] = []
    sharpes: list[float] = []
    for _ in range(n_resamples):
        sample: list[float] = []
        for _b in range(n_blocks_needed):
            start = rng.randrange(0, n - block_size + 1)
            sample.extend(returns[start : start + block_size])
        sample = sample[:n]
        sample_mean = mean(sample)
        means.append(sample_mean)
        cumulatives.append(sum(sample))
        sd = stdev(sample)
        sharpes.append(sample_mean / sd if sd > 0 else 0.0)

    return _bootstrap_report_from_resamples(list(returns), means, cumulatives, sharpes, confidence_level=confidence_level)


def stationary_bootstrap_return_series(returns: Sequence[float], *, mean_block_length: float, n_resamples: int = 2000, seed: int = 42, confidence_level: float = 0.90) -> BootstrapReport:
    """Politis & Romano (1994) stationary bootstrap on a period-return
    series — see placebo.stationary_bootstrap_trade_statistics's
    docstring for the general method."""
    if mean_block_length <= 0:
        raise ValueError("mean_block_length must be > 0")
    n = len(returns)
    if n < MIN_BOOTSTRAP_SAMPLE:
        return BootstrapReport(sample_size=n, insufficient_sample=True, mean_trade_return_ci=None, expectancy_ci=None, cumulative_return_ci=None, sharpe_like_ci=None)

    p_continue = 1.0 / mean_block_length
    rng = random.Random(seed)
    means: list[float] = []
    cumulatives: list[float] = []
    sharpes: list[float] = []
    for _ in range(n_resamples):
        sample: list[float] = []
        while len(sample) < n:
            idx = rng.randrange(n)
            while True:
                sample.append(returns[idx])
                if len(sample) >= n or rng.random() < p_continue:
                    break
                idx = (idx + 1) % n
        sample = sample[:n]
        sample_mean = mean(sample)
        means.append(sample_mean)
        cumulatives.append(sum(sample))
        sd = stdev(sample)
        sharpes.append(sample_mean / sd if sd > 0 else 0.0)

    return _bootstrap_report_from_resamples(list(returns), means, cumulatives, sharpes, confidence_level=confidence_level)
