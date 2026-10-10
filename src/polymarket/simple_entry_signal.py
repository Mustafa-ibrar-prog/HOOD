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

  1. Evaluated continuously across the FULL 15-minute market, at ANY
     point while it is open -- there is no "only in the last N
     minutes" restriction, and (as of this round) NO required
     implied-probability threshold either. The bot does not wait for
     either side to reach any particular percentage before entering.
  2. Direction is simply whichever side the market CURRENTLY FAVORS:
     compare yes_order_book.mid (YES's own implied probability)
     against no_order_book.mid (NO's own) and take the higher one.
     This is never the old ">= 0.70" gate (which blocked entry below
     that level and is gone entirely) and never a guess at WHICH side
     is "right" beyond "the market's own current read."
  3. Exactly tied (or either side's midpoint unavailable -- no
     two-sided quote yet) is NO TRADE -- there is no coin to flip, and
     missing data is never treated as a 50/50 guess.
  4. A SECOND, independent filter on top of 2-3: the gap between the
     two sides (edge = abs(yes_implied_probability -
     no_implied_probability)) must be at least `min_entry_edge`
     (settings.simple_min_entry_edge in production, default 0.10).
     This is NOT the old fixed probability floor reintroduced -- it is
     a RELATIVE requirement on the GAP between both sides, which can
     be satisfied at any probability level (e.g. YES 60%/NO 40%, or
     YES 20%/NO 0% if that were ever possible) and is never applied to
     either side in isolation. A favored side whose edge falls short
     is still NO TRADE, exactly like a tie.
  5. Once a side is selected, its EXECUTION price is a SEPARATE
     concept from the direction decision above: always that side's own
     REAL best_ask (yes_order_book.best_ask for YES, no_order_book.best_ask
     for NO), never the implied probability itself.

`no_order_book` here is always handed in directly (a real,
independent book, or -- for a single-book venue -- the caller's
single_book.to_no_perspective() result); this module never derives
one book from the other itself (see single_book.py's own tests for
that).

This module has NO memory of prior cycles -- the PERSISTENCE
requirement (the same favored, edge-qualified outcome holding for
several consecutive evaluations before an entry is actually allowed)
is a cross-cycle concern layered on top of this pure function's own
per-cycle `outcome`, by the caller (see engine.MarketHistory.
observe_entry_candidate()), never by this module itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.polymarket.models import OrderBookSnapshot

# Pure-function fallback for a direct unit-test call that doesn't care
# about the edge filter -- production ALWAYS passes
# settings.simple_min_entry_edge explicitly (see engine.py). 0.0 means
# "no filter": any non-tied favored side qualifies, same as before
# this round's Change 2 existed.
DEFAULT_MIN_ENTRY_EDGE = 0.0


@dataclass(frozen=True)
class SimpleEntrySignal:
    """The full, inspectable answer -- always attaches every value that
    went into the decision (even on a NO-TRADE result) for full
    auditability in the decision log. Field names deliberately match
    this round's required log vocabulary: YES_BID, YES_ASK,
    MARKET_MIDPOINT, YES_IMPLIED_PROBABILITY, NO_IMPLIED_PROBABILITY,
    SELECTED_OUTCOME, EXECUTABLE_ENTRY_PRICE, EDGE."""

    outcome: str | None  # "YES" | "NO" | None -- SELECTED_OUTCOME (only set once favored AND edge-qualified)
    yes_bid: float | None
    yes_ask: float | None
    market_midpoint: float | None  # yes_order_book.mid
    yes_implied_probability: float | None
    no_implied_probability: float | None
    edge: float | None  # abs(yes_implied_probability - no_implied_probability); None iff either probability is None
    executable_entry_price: float | None  # the REAL ask of whichever side qualified -- never the implied probability
    reason: str

    @property
    def has_candidate(self) -> bool:
        return self.outcome is not None


def assess_simple_entry(
    *,
    yes_order_book: OrderBookSnapshot | None,
    no_order_book: OrderBookSnapshot | None,
    min_entry_edge: float = DEFAULT_MIN_ENTRY_EDGE,
) -> SimpleEntrySignal:
    """Pure and deterministic. Evaluated every cycle the market is
    open -- no time-remaining gate, no fixed probability threshold.
    Picks whichever side the market currently favors (the higher of
    the two implied probabilities); an exact tie, either side's
    midpoint being unavailable, or an insufficient gap between the two
    (edge < min_entry_edge) is NO TRADE. `no_order_book` must already
    be THIS outcome's own real (or, on a single-book venue, correctly
    derived -- see single_book.to_no_perspective()) book; this
    function never re-derives one book from the other itself. Does
    NOT apply the persistence requirement -- see module docstring."""
    yes_bid = yes_order_book.best_bid if yes_order_book is not None else None
    yes_ask = yes_order_book.best_ask if yes_order_book is not None else None
    market_midpoint = yes_order_book.mid if yes_order_book is not None else None
    yes_implied_probability = market_midpoint
    no_implied_probability = no_order_book.mid if no_order_book is not None else None
    no_ask = no_order_book.best_ask if no_order_book is not None else None

    if yes_implied_probability is None or no_implied_probability is None:
        return SimpleEntrySignal(
            outcome=None, yes_bid=yes_bid, yes_ask=yes_ask, market_midpoint=market_midpoint,
            yes_implied_probability=yes_implied_probability, no_implied_probability=no_implied_probability,
            edge=None, executable_entry_price=None,
            reason=(
                f"no two-sided quote available yet (YES implied probability={yes_implied_probability}, "
                f"NO implied probability={no_implied_probability}) -- nothing to favor yet"
            ),
        )

    edge = abs(yes_implied_probability - no_implied_probability)

    if yes_implied_probability == no_implied_probability:
        return SimpleEntrySignal(
            outcome=None, yes_bid=yes_bid, yes_ask=yes_ask, market_midpoint=market_midpoint,
            yes_implied_probability=yes_implied_probability, no_implied_probability=no_implied_probability,
            edge=edge, executable_entry_price=None,
            reason=(
                f"YES and NO implied probabilities are exactly tied ({yes_implied_probability:.4f}) -- "
                "no side is favored, no trade"
            ),
        )

    favored = "YES" if yes_implied_probability > no_implied_probability else "NO"

    if edge < min_entry_edge:
        return SimpleEntrySignal(
            outcome=None, yes_bid=yes_bid, yes_ask=yes_ask, market_midpoint=market_midpoint,
            yes_implied_probability=yes_implied_probability, no_implied_probability=no_implied_probability,
            edge=edge, executable_entry_price=None,
            reason=(
                f"market favors {favored} (YES={yes_implied_probability:.4f}, NO={no_implied_probability:.4f}) "
                f"but the edge {edge:.4f} is below the minimum required {min_entry_edge:.4f} -- "
                "insufficient edge, no trade"
            ),
        )

    if favored == "YES":
        return SimpleEntrySignal(
            outcome="YES", yes_bid=yes_bid, yes_ask=yes_ask, market_midpoint=market_midpoint,
            yes_implied_probability=yes_implied_probability, no_implied_probability=no_implied_probability,
            edge=edge, executable_entry_price=yes_ask,
            reason=(
                f"market currently favors YES (implied probability {yes_implied_probability:.4f} > "
                f"NO's {no_implied_probability:.4f}, edge {edge:.4f}) -- executing at the real ask {yes_ask}"
            ),
        )
    return SimpleEntrySignal(
        outcome="NO", yes_bid=yes_bid, yes_ask=yes_ask, market_midpoint=market_midpoint,
        yes_implied_probability=yes_implied_probability, no_implied_probability=no_implied_probability,
        edge=edge, executable_entry_price=no_ask,
        reason=(
            f"market currently favors NO (implied probability {no_implied_probability:.4f} > "
            f"YES's {yes_implied_probability:.4f}, edge {edge:.4f}) -- executing at the real (short-side) ask {no_ask}"
        ),
    )
