"""Placebo/randomization and bootstrap analysis (Phase 5, sections 14-15).

Both methods here are DETERMINISTIC (fixed seed) — "randomization" means
"a reproducible, seeded pseudo-random draw," never true nondeterminism,
consistent with this codebase's backtesting-determinism requirement
carried over from Phase 3.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from src.backtesting.journal import BacktestTrade
from src.data.bar import Bar
from src.research.analysis import mean, stdev
from src.research.baseline import random_entry_baseline

MIN_BOOTSTRAP_SAMPLE = 20


# ==============================================================================
# PLACEBO TEST (section 14)
# ==============================================================================


@dataclass(frozen=True)
class PlaceboTestResult:
    method: str
    n_trials: int
    seed: int
    observed_statistic: float
    simulated_statistics: tuple[float, ...]
    fraction_as_extreme_or_better: float | None
    interpretation_note: str


def randomized_entry_timing_placebo(
    *,
    observed_trades: Sequence[BacktestTrade],
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    holding_period_bars: int,
    quantity: int,
    n_trials: int = 200,
    seed: int = 42,
    statistic_fn: Callable[[list[float]], float] = lambda pnls: mean(pnls) if pnls else 0.0,
) -> PlaceboTestResult:
    """Preserves exactly what the strategy's own timing choice should be
    judged against: the SAME symbols, the SAME number of trades PER
    SYMBOL, and the SAME holding period — only WHEN each trade enters is
    randomized (uniformly, seeded, reproducible — see
    src.research.baseline.random_entry_baseline). Temporal structure
    within a trade (entry->exit over `holding_period_bars` real,
    consecutive bars) is deliberately preserved; only entry TIMING is
    randomized, so the test stays meaningful for a time-series (never
    shuffles bars themselves, which would destroy exactly the temporal
    structure being tested)."""
    observed_stat = statistic_fn([t.net_pnl for t in observed_trades])
    trades_per_symbol: dict[str, int] = {}
    for t in observed_trades:
        trades_per_symbol[t.symbol] = trades_per_symbol.get(t.symbol, 0) + 1

    simulated: list[float] = []
    for trial in range(n_trials):
        trial_pnls: list[float] = []
        for symbol, n_for_symbol in trades_per_symbol.items():
            bars = bars_by_symbol.get(symbol, [])
            if not bars or n_for_symbol == 0:
                continue
            random_trades = random_entry_baseline(bars, quantity=quantity, holding_period_bars=holding_period_bars, n_trades=n_for_symbol, seed=seed * 1_000_003 + trial)
            trial_pnls.extend(t.net_pnl for t in random_trades)
        simulated.append(statistic_fn(trial_pnls))

    fraction = (sum(1 for s in simulated if s >= observed_stat) / len(simulated)) if simulated else None
    return PlaceboTestResult(
        method="randomized entry timing: same symbols, same per-symbol trade count, same holding period, uniformly random (seeded) entry bar",
        n_trials=n_trials, seed=seed, observed_statistic=observed_stat, simulated_statistics=tuple(simulated),
        fraction_as_extreme_or_better=fraction,
        interpretation_note=(
            "Empirical frequency that RANDOM entry timing matched or beat the strategy's actual result. "
            "NOT a formal p-value — trade returns are not i.i.d. and this doesn't correct for multiple testing. "
            "A low fraction is suggestive that timing matters beyond chance; it is not proof of an edge."
        ),
    )


# ==============================================================================
# BOOTSTRAP CONFIDENCE INTERVALS (section 15)
# ==============================================================================


@dataclass(frozen=True)
class BootstrapCI:
    point_estimate: float
    lower: float
    upper: float
    confidence_level: float


@dataclass(frozen=True)
class BootstrapReport:
    sample_size: int
    insufficient_sample: bool
    mean_trade_return_ci: BootstrapCI | None
    expectancy_ci: BootstrapCI | None
    cumulative_return_ci: BootstrapCI | None
    sharpe_like_ci: BootstrapCI | None

    def render(self) -> str:
        if self.insufficient_sample:
            return f"INSUFFICIENT SAMPLE (n={self.sample_size} < {MIN_BOOTSTRAP_SAMPLE})"
        lines = [f"Bootstrap (n={self.sample_size} trades):"]
        for label, ci in (
            ("Mean trade return", self.mean_trade_return_ci),
            ("Expectancy", self.expectancy_ci),
            ("Cumulative return", self.cumulative_return_ci),
            ("Sharpe-like ratio", self.sharpe_like_ci),
        ):
            if ci is not None:
                lines.append(f"  {label}: {ci.point_estimate:.4f}  [{ci.lower:.4f}, {ci.upper:.4f}] ({ci.confidence_level:.0%} CI)")
        return "\n".join(lines)


def bootstrap_trade_statistics(trades: Sequence[BacktestTrade], *, n_resamples: int = 2000, seed: int = 42, confidence_level: float = 0.90) -> BootstrapReport:
    """Resamples trade-level net P&L WITH REPLACEMENT — the standard i.i.d.
    bootstrap. Caveat, stated rather than hidden: a persistent strategy's
    trade returns can still be serially correlated (e.g. clustered wins
    during a trending regime), which a plain i.i.d. resample doesn't
    account for — these intervals should be read as a rough, reproducible
    sense of estimation uncertainty, not a rigorous confidence guarantee.
    Below MIN_BOOTSTRAP_SAMPLE trades, returns "INSUFFICIENT SAMPLE"
    rather than a misleadingly narrow/wide interval from too few points.
    """
    pnls = [t.net_pnl for t in trades]
    n = len(pnls)
    if n < MIN_BOOTSTRAP_SAMPLE:
        return BootstrapReport(sample_size=n, insufficient_sample=True, mean_trade_return_ci=None, expectancy_ci=None, cumulative_return_ci=None, sharpe_like_ci=None)

    rng = random.Random(seed)
    means: list[float] = []
    cumulatives: list[float] = []
    sharpes: list[float] = []
    for _ in range(n_resamples):
        sample = [pnls[rng.randrange(n)] for _ in range(n)]
        sample_mean = mean(sample)
        means.append(sample_mean)
        cumulatives.append(sum(sample))
        sd = stdev(sample)
        sharpes.append(sample_mean / sd if sd > 0 else 0.0)

    lo_pct = (1 - confidence_level) / 2
    hi_pct = 1 - lo_pct

    def _ci(values: list[float], point: float) -> BootstrapCI:
        values_sorted = sorted(values)
        lo_idx = int(lo_pct * len(values_sorted))
        hi_idx = min(len(values_sorted) - 1, int(hi_pct * len(values_sorted)))
        return BootstrapCI(point_estimate=point, lower=values_sorted[lo_idx], upper=values_sorted[hi_idx], confidence_level=confidence_level)

    observed_mean = mean(pnls)
    observed_sd = stdev(pnls)
    observed_sharpe = observed_mean / observed_sd if observed_sd > 0 else 0.0

    return BootstrapReport(
        sample_size=n, insufficient_sample=False,
        mean_trade_return_ci=_ci(means, observed_mean),
        expectancy_ci=_ci(means, observed_mean),
        cumulative_return_ci=_ci(cumulatives, sum(pnls)),
        sharpe_like_ci=_ci(sharpes, observed_sharpe),
    )
