"""Phase 35, Part C-D — matches each real underlying entry-signal date
(`phase35_underlying_signal.py`) to a REAL, tradable option contract
observation, using the SAME contract-day panel Phase 31/32/33 already
built (`phase31_panel_builder.build_panel_rows`, unmodified).

DATA_LIMITED, DISCLOSED: this project's free dataset has no real,
exhaustive historical option-chain/tradability feed (Phase 26's own
documented finding: `reconstruct_chain_as_of` reconstructs "which
contracts have at least one real quote observation," never a true
vendor-asserted tradable-strike snapshot). So "nearest strike within a
DTE window, as of the signal date" is answered from whichever real
contract-day rows happen to exist near that date -- never a literal
historical chain scan. A signal date with no real matching contract
observation within `date_tolerance_days` produces NO trade (excluded,
counted, and reported as DATA_LIMITED) -- never a fabricated one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from src.options.phase35_frozen_strategy_spec import MOMENTUM_BREAKOUT_EXISTING_V1
from src.options.phase35_underlying_signal import UnderlyingSignalEvent

DEFAULT_DATE_TOLERANCE_DAYS = 5  # how far from the real signal date a real contract observation may be and still count as "the contract you'd have selected that day"


@dataclass(frozen=True)
class MatchedOptionTrade:
    underlying_symbol: str
    signal_date: date
    option_id: str
    expiration: date
    strike: float
    entry_row: dict  # the real contract-day row used as the entry observation
    management_rows: tuple[dict, ...]  # that SAME option_id's own subsequent real rows, sorted by date (may be empty)
    entry_date_offset_days: int  # |entry_row.timestamp.date() - signal_date| -- disclosed, never hidden


def find_matching_contract_trade(
    signal: UnderlyingSignalEvent, contract_day_rows: list[dict], *,
    date_tolerance_days: int = DEFAULT_DATE_TOLERANCE_DAYS,
) -> MatchedOptionTrade | None:
    spec = MOMENTUM_BREAKOUT_EXISTING_V1.option_selection
    candidates = [
        r for r in contract_day_rows
        if r.get("underlying_symbol") == signal.underlying_symbol
        and r.get("call_put") == spec.option_type
        and r.get("dte") is not None
        and spec.min_days_to_expiration <= r["dte"] <= spec.max_days_to_expiration
        and r.get("ask") is not None and r["ask"] > 0
        and abs((r["timestamp"].date() - signal.signal_date).days) <= date_tolerance_days
    ]
    if not candidates:
        return None

    def _rank(r: dict) -> tuple[float, int]:
        strike_distance = abs(r["strike"] - signal.underlying_price)
        date_distance = abs((r["timestamp"].date() - signal.signal_date).days)
        return (strike_distance, date_distance)

    entry_row = min(candidates, key=_rank)
    option_id = entry_row["option_id"]

    same_contract_rows = sorted(
        (r for r in contract_day_rows if r.get("option_id") == option_id and r["timestamp"].date() >= entry_row["timestamp"].date()),
        key=lambda r: r["timestamp"],
    )
    management_rows = tuple(r for r in same_contract_rows if r["timestamp"] != entry_row["timestamp"])

    return MatchedOptionTrade(
        underlying_symbol=signal.underlying_symbol, signal_date=signal.signal_date, option_id=option_id,
        expiration=entry_row["expiration"], strike=entry_row["strike"], entry_row=entry_row,
        management_rows=management_rows,
        entry_date_offset_days=abs((entry_row["timestamp"].date() - signal.signal_date).days),
    )


def match_all_signals(
    signals: tuple[UnderlyingSignalEvent, ...], contract_day_rows: list[dict], *,
    date_tolerance_days: int = DEFAULT_DATE_TOLERANCE_DAYS,
) -> tuple[list[MatchedOptionTrade], list[UnderlyingSignalEvent]]:
    """Returns (matched_trades, unmatched_signals) -- the SAME accounting
    Part C/H require: every signal is either matched to a real, tradeable
    contract, or explicitly counted as unmatched (DATA_LIMITED), never
    silently dropped."""
    matched: list[MatchedOptionTrade] = []
    unmatched: list[UnderlyingSignalEvent] = []
    for signal in signals:
        m = find_matching_contract_trade(signal, contract_day_rows, date_tolerance_days=date_tolerance_days)
        if m is None:
            unmatched.append(signal)
        else:
            matched.append(m)
    return matched, unmatched
