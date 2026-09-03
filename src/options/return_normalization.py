"""Phase 20, Part 13 — option return normalization: several
economically-interpretable ways to express the same (entry, exit) option
trade, each documented so a reader knows exactly what it means and none
of them look ahead past the exit bar they're defined over.

Every function here takes an explicit `bars[entry_index:exit_index+1]`
window (or the equivalent entry/exit values directly) -- MAE/MFE are
computed ONLY from bars strictly between entry and exit (inclusive),
never from anything after the exit index. This is what makes them
causal: a reader who only knew prices up through the exit bar could
compute the identical number.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.options.price_history import OptionPriceBar


@dataclass(frozen=True)
class NormalizedReturn:
    entry_price: float
    exit_price: float
    contract_multiplier: int
    raw_percentage_return: float  # (exit - entry) / entry
    dollar_return_per_contract: float  # (exit - entry) * contract_multiplier
    return_relative_to_premium: float  # dollar_return_per_contract / (entry * contract_multiplier) -- identical to raw_percentage_return by construction, reported separately because Part 13 asks for it as its own named figure
    max_adverse_excursion: float | None  # largest DROP below entry_price observed within [entry_index, exit_index], as a fraction of entry_price (>= 0; None if no bars given)
    max_favorable_excursion: float | None  # largest RISE above entry_price observed within [entry_index, exit_index], as a fraction of entry_price (>= 0; None if no bars given)
    payoff_asymmetry: float | None  # max_favorable_excursion - max_adverse_excursion; positive means the path favored the holder more than it threatened them, before the eventual exit


def compute_normalized_return(bars_window: list[OptionPriceBar], *, contract_multiplier: int = 100) -> NormalizedReturn:
    """`bars_window` is the option's own OHLC bars from entry through
    exit INCLUSIVE (bars_window[0] is the entry bar, bars_window[-1] is
    the exit bar) -- callers must slice this themselves from a real,
    already-observed series; this function never fetches or extends the
    window."""
    if not bars_window:
        raise ValueError("bars_window must contain at least the entry bar")
    entry_price = bars_window[0].close
    exit_price = bars_window[-1].close
    if entry_price <= 0:
        raise ValueError(f"entry_price must be > 0, got {entry_price}")

    raw_return = (exit_price - entry_price) / entry_price
    dollar_return = (exit_price - entry_price) * contract_multiplier
    return_rel_premium = dollar_return / (entry_price * contract_multiplier)

    mae = mfe = asymmetry = None
    if len(bars_window) >= 1:
        lows = [b.low for b in bars_window]
        highs = [b.high for b in bars_window]
        mae = max(0.0, (entry_price - min(lows)) / entry_price)
        mfe = max(0.0, (max(highs) - entry_price) / entry_price)
        asymmetry = mfe - mae

    return NormalizedReturn(
        entry_price=entry_price, exit_price=exit_price, contract_multiplier=contract_multiplier,
        raw_percentage_return=raw_return, dollar_return_per_contract=dollar_return,
        return_relative_to_premium=return_rel_premium, max_adverse_excursion=mae, max_favorable_excursion=mfe,
        payoff_asymmetry=asymmetry,
    )
