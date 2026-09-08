"""Phase 40, Part 18 — end-of-day performance rollup.

A PURE aggregation over the equity curve (`EquitySnapshotStore`) plus
the trade journal — computed on demand, for any date range, rather than
a stateful "did we cross midnight" trigger (which would need a
scheduler this project explicitly does not build). Calling this after
every real cycle for "today so far" and again at the end of the
experiment for the full history are the same function.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from src.paper_trading.equity_curve import EquitySnapshotRecord
from src.paper_trading.journal import PaperExperimentTradeRecord


@dataclass(frozen=True)
class DailyPerformanceRecord:
    trade_date: date
    starting_equity_usd: float
    ending_equity_usd: float
    daily_pnl_usd: float
    daily_return_pct: float
    trades_opened: int
    trades_closed: int
    wins: int
    losses: int
    open_positions_at_close: int
    max_intraday_drawdown_pct: float | None  # None if fewer than 2 snapshots that day


def compute_daily_performance(
    equity_snapshots: Sequence[EquitySnapshotRecord], trades: Sequence[PaperExperimentTradeRecord],
) -> list[DailyPerformanceRecord]:
    by_date: dict[date, list[EquitySnapshotRecord]] = {}
    for snap in equity_snapshots:
        by_date.setdefault(snap.timestamp.date(), []).append(snap)

    records: list[DailyPerformanceRecord] = []
    for d in sorted(by_date):
        rows = sorted(by_date[d], key=lambda r: r.timestamp)
        starting_equity = rows[0].equity_usd
        ending_equity = rows[-1].equity_usd
        daily_pnl = ending_equity - starting_equity
        daily_return = (daily_pnl / starting_equity) if starting_equity else 0.0

        opened = sum(1 for t in trades if t.entry_timestamp.date() == d)
        closed_today = [t for t in trades if t.exit_timestamp is not None and t.exit_timestamp.date() == d]
        wins = sum(1 for t in closed_today if (t.net_pnl_usd or 0.0) > 0)
        losses = sum(1 for t in closed_today if (t.net_pnl_usd or 0.0) < 0)

        max_intraday_dd = None
        if len(rows) >= 2:
            peak = rows[0].equity_usd
            worst = 0.0
            for r in rows:
                peak = max(peak, r.equity_usd)
                if peak > 0:
                    worst = max(worst, (peak - r.equity_usd) / peak)
            max_intraday_dd = worst

        records.append(DailyPerformanceRecord(
            trade_date=d, starting_equity_usd=starting_equity, ending_equity_usd=ending_equity,
            daily_pnl_usd=round(daily_pnl, 2), daily_return_pct=daily_return, trades_opened=opened,
            trades_closed=len(closed_today), wins=wins, losses=losses,
            open_positions_at_close=rows[-1].open_positions, max_intraday_drawdown_pct=max_intraday_dd,
        ))
    return records
