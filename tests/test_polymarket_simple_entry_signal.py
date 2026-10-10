"""Focused tests for simple_entry_signal.py -- the ONLY production
entry-direction logic as of this round. There is NO probability
threshold any more: direction is simply whichever side the market
CURRENTLY FAVORS (the higher of YES's and NO's own implied
probabilities, each book's own midpoint). Evaluated continuously
across the FULL 15-minute market, at any point while it is open.
EXECUTION price is a separate concept, always the real best_ask of
whichever side is favored. Pure-function tests against hand-built
OrderBookSnapshot values -- no run_cycle needed."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.polymarket.models import BookLevel, OrderBookSnapshot
from src.polymarket.simple_entry_signal import assess_simple_entry

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _book(*, bid: float | None, ask: float | None) -> OrderBookSnapshot:
    bids = (BookLevel(price=bid, size=1000.0),) if bid is not None else ()
    asks = (BookLevel(price=ask, size=1000.0),) if ask is not None else ()
    return OrderBookSnapshot(token_id="t", bids=bids, asks=asks, fetched_at=_NOW)


def _symmetric_book(price: float | None) -> OrderBookSnapshot:
    """A zero-spread book (bid == ask) -- its midpoint equals the ask
    exactly, which keeps these fixtures simple when the bid/ask
    distinction isn't what's under test."""
    return _book(bid=price, ask=price)


# --- A: there is no probability threshold any more -- a market barely
# favoring one side still enters (this is the core behavior change this
# round makes: the old ">= 0.70" gate is gone entirely). ---------------

def test_a_a_market_barely_favoring_yes_still_enters_yes():
    # YES mid 0.51 vs NO mid 0.49 -- nowhere near the old 0.70 gate, but
    # YES is still the favored side, so it enters.
    result = assess_simple_entry(yes_order_book=_symmetric_book(0.51), no_order_book=_symmetric_book(0.49))
    assert result.outcome == "YES"


def test_a2_a_market_barely_favoring_no_still_enters_no():
    result = assess_simple_entry(yes_order_book=_symmetric_book(0.49), no_order_book=_symmetric_book(0.51))
    assert result.outcome == "NO"


def test_a3_the_function_never_looks_at_time_its_a_pure_book_function():
    # No time parameter exists at all -- entry is allowed at any point
    # during the 15-minute market purely by never gating on time here.
    result = assess_simple_entry(yes_order_book=_symmetric_book(0.80), no_order_book=_symmetric_book(0.10))
    assert result.outcome == "YES"


# --- B: direction is whichever side the market currently favors ------------

def test_b_yes_favored_by_a_wide_margin_selects_yes():
    result = assess_simple_entry(yes_order_book=_symmetric_book(0.80), no_order_book=_symmetric_book(0.10))
    assert result.outcome == "YES"


def test_b2_no_favored_by_a_wide_margin_selects_no():
    result = assess_simple_entry(yes_order_book=_symmetric_book(0.10), no_order_book=_symmetric_book(0.80))
    assert result.outcome == "NO"


def test_b3_exactly_tied_is_no_trade():
    result = assess_simple_entry(yes_order_book=_symmetric_book(0.50), no_order_book=_symmetric_book(0.50))
    assert result.outcome is None


# --- C: execution price is a REAL ask, separate from the direction read ---

def test_c_execution_price_is_the_real_ask_not_the_implied_probability():
    book = _book(bid=0.65, ask=0.75)  # mid 0.70 -- still just "favored," no threshold meaning to 0.70 here
    result = assess_simple_entry(yes_order_book=book, no_order_book=_symmetric_book(0.10))
    assert result.yes_implied_probability == 0.70
    assert result.outcome == "YES"
    assert result.executable_entry_price == 0.75  # the real ask, NOT 0.70


def test_c2_no_side_executes_at_its_own_real_ask():
    yes_book = _symmetric_book(0.20)
    no_book = _book(bid=0.70, ask=0.82)  # NO mid 0.76, favored; its own real ask is 0.82
    result = assess_simple_entry(yes_order_book=yes_book, no_order_book=no_book)
    assert result.outcome == "NO"
    assert result.executable_entry_price == 0.82


# --- D: missing book data is always NO TRADE, never a 50/50 guess ---------

def test_d_no_yes_order_book_at_all_is_no_trade():
    result = assess_simple_entry(yes_order_book=None, no_order_book=_symmetric_book(0.60))
    assert result.outcome is None
    assert result.yes_implied_probability is None


def test_d2_no_no_order_book_at_all_is_no_trade():
    result = assess_simple_entry(yes_order_book=_symmetric_book(0.60), no_order_book=None)
    assert result.outcome is None
    assert result.no_implied_probability is None


def test_d3_one_sided_book_with_no_bid_has_no_midpoint_so_no_trade():
    book = _book(bid=None, ask=0.90)  # ask-only -- mid is None, never guessed from ask alone
    result = assess_simple_entry(yes_order_book=book, no_order_book=_symmetric_book(0.10))
    assert result.market_midpoint is None
    assert result.yes_implied_probability is None
    assert result.outcome is None


# --- E: full logging vocabulary is always populated ------------------------

def test_e_signal_carries_every_required_logging_field():
    book = _book(bid=0.65, ask=0.75)
    result = assess_simple_entry(yes_order_book=book, no_order_book=_symmetric_book(0.10))
    assert result.yes_bid == 0.65
    assert result.yes_ask == 0.75
    assert result.market_midpoint == 0.70
    assert result.yes_implied_probability == 0.70
    assert result.no_implied_probability == 0.10
    assert result.edge == pytest.approx(0.60)
    assert result.outcome == "YES"
    assert result.executable_entry_price == 0.75


# --- F: minimum entry edge filter -- a SECOND, independent filter on
# top of the favored-side rule above; `min_entry_edge` defaults to 0.0
# (no filter) for a direct unit-test call, so tests A/B/C/D/E above are
# unaffected -- production always passes settings.simple_min_entry_edge
# explicitly (see engine.py). ------------------------------------------

def test_f_insufficient_edge_is_no_trade_even_though_a_side_is_favored():
    # YES 52% / NO 48% -- YES is favored, but the edge (0.04) is below
    # the configured minimum (0.10): no trade, never a coin flip.
    result = assess_simple_entry(
        yes_order_book=_symmetric_book(0.52), no_order_book=_symmetric_book(0.48), min_entry_edge=0.10,
    )
    assert result.outcome is None
    assert result.edge == pytest.approx(0.04)
    assert "insufficient edge" in result.reason


def test_f2_a_sufficient_edge_still_enters():
    # YES 60% / NO 40% -- edge 0.20, comfortably above the 0.10 minimum.
    result = assess_simple_entry(
        yes_order_book=_symmetric_book(0.60), no_order_book=_symmetric_book(0.40), min_entry_edge=0.10,
    )
    assert result.outcome == "YES"
    assert result.edge == pytest.approx(0.20)


def test_f3_exact_threshold_boundary_is_inclusive():
    # edge == min_entry_edge exactly qualifies -- the boundary is
    # ">=", never a strict ">". min_entry_edge is derived from the
    # SAME computation assess_simple_entry itself will do, never a
    # separately hand-typed literal -- 0.60 - 0.40 is not exactly
    # 0.20 in float, so a literal 0.20 could land a hair on the wrong
    # side of this exact boundary and spuriously fail.
    yes_book = _symmetric_book(0.60)
    no_book = _symmetric_book(0.40)
    edge = abs(yes_book.mid - no_book.mid)
    result = assess_simple_entry(yes_order_book=yes_book, no_order_book=no_book, min_entry_edge=edge)
    assert result.outcome == "YES"
    assert result.edge == pytest.approx(edge)


def test_f4_just_below_the_threshold_boundary_is_no_trade():
    # edge 0.19999... just under a 0.20 minimum -- no trade.
    result = assess_simple_entry(
        yes_order_book=_book(bid=0.5999, ask=0.5999), no_order_book=_symmetric_book(0.40), min_entry_edge=0.20,
    )
    assert result.outcome is None
    assert result.edge < 0.20


def test_f5_min_entry_edge_of_zero_disables_the_filter_entirely():
    # Same barely-favoring market as test_a -- min_entry_edge=0.0
    # explicitly reproduces the threshold-free, no-edge-filter behavior.
    result = assess_simple_entry(
        yes_order_book=_symmetric_book(0.51), no_order_book=_symmetric_book(0.49), min_entry_edge=0.0,
    )
    assert result.outcome == "YES"


def test_f6_no_side_favored_by_enough_edge_also_enters():
    result = assess_simple_entry(
        yes_order_book=_symmetric_book(0.30), no_order_book=_symmetric_book(0.70), min_entry_edge=0.10,
    )
    assert result.outcome == "NO"
    assert result.edge == pytest.approx(0.40)


def test_f7_an_exact_tie_is_no_trade_regardless_of_min_entry_edge():
    # A tie is ALREADY no trade before this filter existed (test_b3) --
    # confirmed here that passing min_entry_edge=0.0 (no filter at all)
    # doesn't somehow turn a tie into a coin flip.
    result = assess_simple_entry(
        yes_order_book=_symmetric_book(0.50), no_order_book=_symmetric_book(0.50), min_entry_edge=0.0,
    )
    assert result.outcome is None
    assert result.edge == pytest.approx(0.0)


def test_f8_missing_book_data_is_no_trade_regardless_of_min_entry_edge():
    # Missing data short-circuits before the edge is even computed --
    # confirmed here that passing a min_entry_edge doesn't change that.
    result = assess_simple_entry(yes_order_book=None, no_order_book=_symmetric_book(0.60), min_entry_edge=0.0)
    assert result.outcome is None
    assert result.edge is None
