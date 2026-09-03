"""Phase 26, Part 6 — bid/ask and liquidity certification, computed from
the real ingested quote/trade observations. Every number here is
computed directly from actually-downloaded QuantConnect/Lean sample
data -- nothing is estimated or assumed.
"""

from __future__ import annotations

import enum
import statistics
from dataclasses import dataclass

from src.options.phase26_dataset_builder import InMemoryLeanSampleStore


class ExecutionRealismGrade(enum.Enum):
    A = "a_historical_quotes_and_trade_data"
    B = "b_historical_bid_ask_only"
    C = "c_trades_only"
    D = "d_ohlc_only"
    F = "f_insufficient"


@dataclass(frozen=True)
class ExecutionRealismReport:
    contract_id: str
    n_quote_snapshots: int
    n_trades: int
    mean_spread_dollars: float | None
    mean_spread_pct_of_mid: float | None
    mean_bid_to_mid_distance: float | None
    mean_ask_to_mid_distance: float | None
    quote_availability_rate: float | None  # fraction of expected snapshots with a real bid AND ask present
    zero_or_invalid_quote_rate: float | None  # fraction with bid<=0 or ask<=0 or bid>ask
    trades_inside_spread_rate: float | None  # fraction of trades priced within [bid, ask] at same timestamp
    grade: ExecutionRealismGrade


def _all_quote_rows(store: InMemoryLeanSampleStore, contract_id: str) -> list[tuple[float | None, float | None]]:
    """Every real quote ROW this contract has (bid, ask) -- one or both
    may be None (a genuinely one-sided market that day, a real finding
    this phase, see phase26_lean_sample_parser's `_parse_optional_
    decicents`), never coerced to 0.0."""
    obs = store.quotes.get(contract_id, [])
    bids = {o.timestamps.event_time: o.value for o in obs if o.field == "bid"}
    asks = {o.timestamps.event_time: o.value for o in obs if o.field == "ask"}
    # .get(ts) rather than [ts]: a row may carry only one side's *observation
    # record* at all (not merely a None value on both) -- either shape means
    # "no quote on that side," and both must be treated identically, never a
    # KeyError.
    return [(bids.get(ts), asks.get(ts)) for ts in sorted(bids.keys() | asks.keys())]


def build_execution_realism_report(store: InMemoryLeanSampleStore, contract_id: str) -> ExecutionRealismReport:
    all_rows = _all_quote_rows(store, contract_id)
    two_sided = [(b, a) for b, a in all_rows if b is not None and a is not None]
    trades = store.trades.get(contract_id, [])
    trade_prices = {o.timestamps.event_time: o.value for o in trades if o.field == "price"}

    if not all_rows and not trades:
        return ExecutionRealismReport(contract_id, 0, 0, None, None, None, None, None, None, None, ExecutionRealismGrade.F)

    valid = [(b, a) for b, a in two_sided if b > 0 and a > 0 and b <= a]
    invalid_count = len(all_rows) - len(valid)  # one-sided rows AND crossed/non-positive two-sided rows both count as invalid-for-spread-purposes

    spreads_dollars = [a - b for b, a in valid]
    mids = [(a + b) / 2 for b, a in valid]
    spreads_pct = [((a - b) / m) for (b, a), m in zip(valid, mids) if m > 0]
    bid_dist = [(m - b) for (b, a), m in zip(valid, mids)]
    ask_dist = [(a - m) for (b, a), m in zip(valid, mids)]

    inside_flags = []
    obs_ts = {o.timestamps.event_time for o in store.quotes.get(contract_id, [])}
    bid_by_ts = {o.timestamps.event_time: o.value for o in store.quotes.get(contract_id, []) if o.field == "bid"}
    ask_by_ts = {o.timestamps.event_time: o.value for o in store.quotes.get(contract_id, []) if o.field == "ask"}
    for ts, price in trade_prices.items():
        b, a = bid_by_ts.get(ts), ask_by_ts.get(ts)
        if b is not None and a is not None:
            inside_flags.append(b <= price <= a)

    has_quotes = len(all_rows) > 0
    has_trades = len(trades) > 0
    if has_quotes and has_trades:
        grade = ExecutionRealismGrade.A
    elif has_quotes:
        grade = ExecutionRealismGrade.B
    elif has_trades:
        grade = ExecutionRealismGrade.C
    else:
        grade = ExecutionRealismGrade.F

    return ExecutionRealismReport(
        contract_id=contract_id,
        n_quote_snapshots=len(all_rows),
        n_trades=len(trades) // 5 if trades else 0,  # 5 observations per trade bar (open/high/low/close/volume)
        mean_spread_dollars=statistics.mean(spreads_dollars) if spreads_dollars else None,
        mean_spread_pct_of_mid=statistics.mean(spreads_pct) if spreads_pct else None,
        mean_bid_to_mid_distance=statistics.mean(bid_dist) if bid_dist else None,
        mean_ask_to_mid_distance=statistics.mean(ask_dist) if ask_dist else None,
        quote_availability_rate=(len(two_sided) / len(all_rows)) if all_rows else None,  # fraction of real rows with BOTH sides quoted
        zero_or_invalid_quote_rate=(invalid_count / len(all_rows)) if all_rows else None,
        trades_inside_spread_rate=(sum(inside_flags) / len(inside_flags)) if inside_flags else None,
        grade=grade,
    )
