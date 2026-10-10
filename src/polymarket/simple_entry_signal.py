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
  2. The ENTRY TRIGGER is the market's IMPLIED PROBABILITY, never the
     raw ask: yes_implied_probability = yes_order_book.mid (the
     midpoint of YES's own real bid/ask -- what the market is actually
     pricing YES's chance at), and no_implied_probability =
     no_order_book.mid (the midpoint of NO's own real bid/ask -- its
     OWN book's midpoint, never fabricated as `1 - yes_mid`, since on
     a venue with two genuinely independent books the two need not sum
     to exactly 1.0; on a venue with only ONE real book (Polymarket
     US), the caller -- engine.py -- is responsible for deriving NO's
     own book from that one real book via single_book.to_no_perspective()
     before calling this function, which makes the two midpoints sum
     to exactly 1.0 by construction and is what actually fixes the
     "identical YES/NO readings" bug -- this function itself never
     special-cases a venue or re-derives one book from the other).
  3. YES is the candidate when yes_implied_probability >= ask_threshold
     (0.70 by default) -- the EXECUTION price is separate from this
     trigger: the real executable ask (yes_order_book.best_ask), never
     the implied probability itself. A $0.75 ask with a $0.65 bid (mid
     $0.70) still qualifies at exactly the $0.75 ask.
  4. NO is the candidate symmetrically from no_order_book, with its own
     real best_ask as the execution price.
  5. Both qualifying simultaneously is treated as a conflicting/invalid
     setup -- NO TRADE. On a correctly-derived single-book NO view this
     is structurally impossible (the two midpoints always sum to
     1.0), so this branch is purely defensive: a crossed/inverted
     source book (bid > ask) could otherwise produce exactly this
     nonsensical reading, and "no trade" is always the safe response to
     that, never a guess at which one "really" qualifies.
  6. Neither qualifying -- NO TRADE.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.polymarket.models import OrderBookSnapshot

DEFAULT_ASK_THRESHOLD = 0.70


@dataclass(frozen=True)
class SimpleEntrySignal:
    """The full, inspectable answer -- always attaches every value that
    went into the decision (even on a NO-TRADE result) for full
    auditability in the decision log. Field names deliberately match
    this round's required log vocabulary: YES_BID, YES_ASK,
    MARKET_MIDPOINT, YES_IMPLIED_PROBABILITY, NO_IMPLIED_PROBABILITY,
    SELECTED_OUTCOME, EXECUTABLE_ENTRY_PRICE."""

    outcome: str | None  # "YES" | "NO" | None -- SELECTED_OUTCOME
    yes_bid: float | None
    yes_ask: float | None
    market_midpoint: float | None  # yes_order_book.mid
    yes_implied_probability: float | None
    no_implied_probability: float | None
    executable_entry_price: float | None  # the REAL ask of whichever side qualified -- never the implied probability
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
    open -- no time-remaining gate. `no_order_book` must already be
    THIS outcome's own real (or, on a single-book venue, correctly
    derived -- see single_book.to_no_perspective()) book; this
    function never re-derives one book from the other itself."""
    yes_bid = yes_order_book.best_bid if yes_order_book is not None else None
    yes_ask = yes_order_book.best_ask if yes_order_book is not None else None
    market_midpoint = yes_order_book.mid if yes_order_book is not None else None
    yes_implied_probability = market_midpoint
    no_implied_probability = no_order_book.mid if no_order_book is not None else None
    no_ask = no_order_book.best_ask if no_order_book is not None else None

    yes_qualifies = yes_implied_probability is not None and yes_implied_probability >= ask_threshold
    no_qualifies = no_implied_probability is not None and no_implied_probability >= ask_threshold

    if yes_qualifies and no_qualifies:
        return SimpleEntrySignal(
            outcome=None, yes_bid=yes_bid, yes_ask=yes_ask, market_midpoint=market_midpoint,
            yes_implied_probability=yes_implied_probability, no_implied_probability=no_implied_probability,
            executable_entry_price=None,
            reason=(
                f"both YES implied probability ({yes_implied_probability:.4f}) and NO implied probability "
                f"({no_implied_probability:.4f}) are >= {ask_threshold:.2f} -- conflicting/invalid book, no trade"
            ),
        )
    if yes_qualifies:
        return SimpleEntrySignal(
            outcome="YES", yes_bid=yes_bid, yes_ask=yes_ask, market_midpoint=market_midpoint,
            yes_implied_probability=yes_implied_probability, no_implied_probability=no_implied_probability,
            executable_entry_price=yes_ask,
            reason=(
                f"YES implied probability {yes_implied_probability:.4f} >= {ask_threshold:.2f} threshold -- "
                f"executing at the real ask {yes_ask}"
            ),
        )
    if no_qualifies:
        return SimpleEntrySignal(
            outcome="NO", yes_bid=yes_bid, yes_ask=yes_ask, market_midpoint=market_midpoint,
            yes_implied_probability=yes_implied_probability, no_implied_probability=no_implied_probability,
            executable_entry_price=no_ask,
            reason=(
                f"NO implied probability {no_implied_probability:.4f} >= {ask_threshold:.2f} threshold -- "
                f"executing at the real (short-side) ask {no_ask}"
            ),
        )
    return SimpleEntrySignal(
        outcome=None, yes_bid=yes_bid, yes_ask=yes_ask, market_midpoint=market_midpoint,
        yes_implied_probability=yes_implied_probability, no_implied_probability=no_implied_probability,
        executable_entry_price=None,
        reason=(
            f"neither YES implied probability ({yes_implied_probability}) nor NO implied probability "
            f"({no_implied_probability}) reach the {ask_threshold:.2f} threshold"
        ),
    )
