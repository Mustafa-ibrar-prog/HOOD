"""Baseline comparisons (Phase 4, section 18) — every strategy result
must be judged against something trivial, not just "did it make money."
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence

from src.backtesting.portfolio import EquityPoint, Portfolio
from src.data.bar import Bar


def buy_and_hold_curve(bars: Sequence[Bar], *, starting_cash: float) -> list[EquityPoint]:
    """Buys as many whole shares as affordable at the FIRST bar's open,
    holds unconditionally, marks to market every subsequent bar. Uses
    Phase 3's real Portfolio class — genuine reuse, not a re-derivation."""
    if not bars:
        return []
    portfolio = Portfolio(starting_cash)
    first = bars[0]
    quantity = int(starting_cash // first.open)
    if quantity > 0:
        portfolio.apply_buy_fill(symbol=first.symbol, quantity=quantity, execution_price=first.open, fees=0.0)
    for bar in bars:
        portfolio.mark_to_market(prices={first.symbol: bar.close}, timestamp=bar.timestamp)
    return portfolio.equity_curve


def no_trade_curve(bars: Sequence[Bar], *, starting_cash: float) -> list[EquityPoint]:
    """Cash the entire period — the trivial "did nothing" comparison."""
    portfolio = Portfolio(starting_cash)
    return [portfolio.mark_to_market(prices={}, timestamp=bar.timestamp) for bar in bars]


@dataclass(frozen=True)
class RandomEntryTrade:
    entry_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    net_pnl: float


def random_entry_baseline(bars: Sequence[Bar], *, quantity: int, holding_period_bars: int, n_trades: int, seed: int) -> list[RandomEntryTrade]:
    """A DETERMINISTIC (seeded, never truly random) baseline: `n_trades`
    entries at uniformly random bar indices, each held for exactly
    `holding_period_bars`, no overlap constraint enforced (a real
    random-entry baseline doesn't need one — it's answering "does the
    strategy's specific ENTRY TIMING beat picking bars at random",
    holding period held constant to isolate that one variable)."""
    if len(bars) <= holding_period_bars:
        return []
    rng = random.Random(seed)
    trades = []
    max_entry_index = len(bars) - holding_period_bars - 1
    if max_entry_index < 0:
        return []
    for _ in range(n_trades):
        entry_index = rng.randint(0, max_entry_index)
        exit_index = entry_index + holding_period_bars
        entry_price = bars[entry_index].open
        exit_price = bars[exit_index].open
        trades.append(RandomEntryTrade(entry_index=entry_index, exit_index=exit_index, entry_price=entry_price, exit_price=exit_price, net_pnl=(exit_price - entry_price) * quantity))
    return trades
