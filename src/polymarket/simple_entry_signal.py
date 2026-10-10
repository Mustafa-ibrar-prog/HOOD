"""The ONLY production entry-direction signal as of this round: a
simple, deliberately dumb Polymarket-price-based rule, replacing
Coinbase BTC intelligence / the settlement-reference divergence check /
confidence scoring / historical learning entirely for the live entry
decision (see engine.py's module docstring for the full list of what
no longer runs in production).

btc_entry_signal.py / entry_confidence.py / trade_learning.py /
reference_divergence.py are all left in place, unmodified, with their
own tests intact -- this is a deliberate choice NOT to delete useful
infrastructure that may be wanted again later. engine.py simply no
longer calls any of them.

RULE (verbatim, intentionally simple -- never second-guessed by BTC
momentum, RSI, MACD, EMA, confidence, or historical learning):

  1. Evaluated continuously across the FULL 15-minute market -- there
     is no "only in the last N minutes" restriction any more; every
     cycle for which the market is still open is evaluated.
  2. YES is the candidate when YES's own order book's REAL executable
     ask (OrderBookSnapshot.best_ask -- never BinaryMarket.yes_ask,
     which can be a stale top-of-book snapshot from market discovery,
     and never the mid) is >= ask_threshold (0.70 by default).
  3. NO is the candidate symmetrically, from NO's own order book.
  4. Both qualifying simultaneously is treated as a conflicting/
     invalid setup -- NO TRADE, never resolved by guessing which one
     "wins."
  5. Neither qualifying -- NO TRADE.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.polymarket.models import OrderBookSnapshot

DEFAULT_ASK_THRESHOLD = 0.70


@dataclass(frozen=True)
class SimpleEntrySignal:
    """The full, inspectable answer -- always attaches whatever
    yes_ask/no_ask were actually observed (even on a NO-TRADE result)
    for full auditability in the decision log."""

    outcome: str | None  # "YES" | "NO" | None
    yes_ask: float | None
    no_ask: float | None
    reason: str

    @property
    def has_candidate(self) -> bool:
        return self.outcome is not None


def assess_simple_entry(
    *,
    yes_order_book: OrderBookSnapshot | None,
    no_order_book: OrderBookSnapshot | None,
    ask_threshold: float = DEFAULT_ASK_THRESHOLD,
) -> SimpleEntrySignal:
    """Pure and deterministic. Evaluated every cycle the market is
    open -- no time-remaining gate; the caller (engine.py) decides
    only WHETHER a market is still open, never WHEN within its
    lifetime to evaluate."""
    yes_ask = yes_order_book.best_ask if yes_order_book is not None else None
    no_ask = no_order_book.best_ask if no_order_book is not None else None
    yes_qualifies = yes_ask is not None and yes_ask >= ask_threshold
    no_qualifies = no_ask is not None and no_ask >= ask_threshold

    if yes_qualifies and no_qualifies:
        return SimpleEntrySignal(
            outcome=None, yes_ask=yes_ask, no_ask=no_ask,
            reason=(
                f"both YES ask ({yes_ask:.4f}) and NO ask ({no_ask:.4f}) are >= {ask_threshold:.2f} -- "
                "conflicting/invalid setup, no trade"
            ),
        )
    if yes_qualifies:
        return SimpleEntrySignal(
            outcome="YES", yes_ask=yes_ask, no_ask=no_ask,
            reason=f"YES ask {yes_ask:.4f} >= {ask_threshold:.2f} threshold",
        )
    if no_qualifies:
        return SimpleEntrySignal(
            outcome="NO", yes_ask=yes_ask, no_ask=no_ask,
            reason=f"NO ask {no_ask:.4f} >= {ask_threshold:.2f} threshold",
        )
    return SimpleEntrySignal(
        outcome=None, yes_ask=yes_ask, no_ask=no_ask,
        reason=(
            f"neither YES ask ({yes_ask if yes_ask is not None else 'n/a'}) nor NO ask "
            f"({no_ask if no_ask is not None else 'n/a'}) reach the {ask_threshold:.2f} threshold"
        ),
    )
