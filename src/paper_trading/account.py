"""Phase 40, Part 3 — the $1,000 paper-experiment account.

"Never allow unexplained balance changes" (Part 3's explicit
requirement) is enforced structurally, not by convention:
`compute_account_snapshot` is a PURE function of the experiment's full
trade history (`PaperExperimentTradeStore`) plus its currently-open
positions (reused, unmodified, from
`src.position_manager.store.PaperPositionStore`) plus the latest real
quote for each open position. Cash/equity are always RE-DERIVED from
that ledger every time this is called — there is no separate mutable
"current balance" field anywhere in this package that could drift from
what the trade history actually says.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

from src.config.constants import CONTRACT_MULTIPLIER


@dataclass(frozen=True)
class PaperExperimentAccountSnapshot:
    as_of: datetime
    starting_cash_usd: float
    cash_usd: float  # starting_cash + realized P&L (net) - capital currently committed to open positions
    open_position_market_value_usd: float  # sum of (current bid * qty * multiplier) for open positions -- executable value, never mid
    equity_usd: float  # cash + open_position_market_value
    realized_pnl_usd: float  # sum of net_pnl_usd across all CLOSED trades
    unrealized_pnl_usd: float  # sum over open positions of (current bid - entry_fill) * qty * multiplier
    total_return_pct: float  # (equity - starting_cash) / starting_cash
    peak_equity_usd: float
    max_drawdown_pct: float  # largest peak-to-trough decline in equity observed across the whole equity history supplied
    current_drawdown_pct: float  # (peak_equity - equity) / peak_equity, 0 if at/above peak
    open_position_count: int
    positions_missing_a_current_quote: tuple[str, ...]  # option_ids whose market value could not be marked (no real quote this cycle) -- valued at 0, never guessed

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(), "starting_cash_usd": self.starting_cash_usd, "cash_usd": self.cash_usd,
            "open_position_market_value_usd": self.open_position_market_value_usd, "equity_usd": self.equity_usd,
            "realized_pnl_usd": self.realized_pnl_usd, "unrealized_pnl_usd": self.unrealized_pnl_usd,
            "total_return_pct": self.total_return_pct, "peak_equity_usd": self.peak_equity_usd,
            "max_drawdown_pct": self.max_drawdown_pct, "current_drawdown_pct": self.current_drawdown_pct,
            "open_position_count": self.open_position_count,
            "positions_missing_a_current_quote": list(self.positions_missing_a_current_quote),
        }


def compute_account_snapshot(
    *,
    as_of: datetime,
    starting_cash_usd: float,
    closed_trades: list,  # list[PaperExperimentTradeRecord] with exit_fill set
    open_positions: list,  # list[src.position_manager.models.OpenPosition]
    current_bid_by_option_id: Mapping[str, float],  # real, this-cycle bids only -- never a stale or fabricated value
    historical_peak_equity_usd: float | None = None,  # the running peak from prior snapshots, if any (for max_drawdown_pct across the whole experiment)
) -> PaperExperimentAccountSnapshot:
    realized_pnl = sum(t.net_pnl_usd for t in closed_trades if t.net_pnl_usd is not None)

    open_market_value = 0.0
    unrealized_pnl = 0.0
    missing_quotes: list[str] = []
    cash_committed_to_open_positions = 0.0
    for pos in open_positions:
        cash_committed_to_open_positions += pos.entry_price * pos.quantity * pos.contract_multiplier
        bid = current_bid_by_option_id.get(pos.option_id)
        if bid is None:
            missing_quotes.append(pos.option_id)
            continue  # valued at 0 contribution -- never guessed at the last-known or entry price
        open_market_value += bid * pos.quantity * pos.contract_multiplier
        unrealized_pnl += (bid - pos.entry_price) * pos.quantity * pos.contract_multiplier

    cash = starting_cash_usd + realized_pnl - cash_committed_to_open_positions
    equity = cash + open_market_value
    total_return_pct = (equity - starting_cash_usd) / starting_cash_usd if starting_cash_usd else 0.0

    peak_equity = max(equity, historical_peak_equity_usd) if historical_peak_equity_usd is not None else equity
    current_drawdown_pct = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
    # max_drawdown_pct across THIS single snapshot is the same as current_drawdown_pct (a running
    # max-so-far is computed by the caller across a SEQUENCE of snapshots -- see equity_curve.py's
    # rolling_max_drawdown, reused rather than recomputed here from a single point).
    max_drawdown_pct = current_drawdown_pct

    return PaperExperimentAccountSnapshot(
        as_of=as_of, starting_cash_usd=starting_cash_usd, cash_usd=round(cash, 2),
        open_position_market_value_usd=round(open_market_value, 2), equity_usd=round(equity, 2),
        realized_pnl_usd=round(realized_pnl, 2), unrealized_pnl_usd=round(unrealized_pnl, 2),
        total_return_pct=total_return_pct, peak_equity_usd=round(peak_equity, 2),
        max_drawdown_pct=max_drawdown_pct, current_drawdown_pct=current_drawdown_pct,
        open_position_count=len(open_positions), positions_missing_a_current_quote=tuple(missing_quotes),
    )


def available_cash_for_new_position(snapshot: PaperExperimentAccountSnapshot) -> float:
    """Never negative (Part 14) -- cash_usd is already the real, derived
    remaining balance; this just guards against a caller treating a
    (should-be-impossible) negative value as spendable."""
    return max(0.0, snapshot.cash_usd)
