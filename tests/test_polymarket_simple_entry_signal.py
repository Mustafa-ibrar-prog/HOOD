"""Focused tests for simple_entry_signal.py -- the ONLY production
entry-direction logic as of this round. The ENTRY TRIGGER is the
market's IMPLIED PROBABILITY (each order book's own midpoint), never
the raw ask -- EXECUTION price is a separate concept, always the real
best_ask of whichever side qualifies. Evaluated continuously across
the FULL 15-minute market -- there is no time-remaining restriction.
Pure-function tests against hand-built OrderBookSnapshot values -- no
run_cycle needed. `no_order_book` here is always handed in directly
(a real, independent book, or -- for a single-book venue -- the
caller's single_book.to_no_perspective() result); this module never
derives one book from the other itself (see single_book.py's own
tests for that)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.polymarket.models import BookLevel, OrderBookSnapshot
from src.polymarket.simple_entry_signal import DEFAULT_ASK_THRESHOLD, assess_simple_entry

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _book(*, bid: float | None, ask: float | None) -> OrderBookSnapshot:
    bids = (BookLevel(price=bid, size=1000.0),) if bid is not None else ()
    asks = (BookLevel(price=ask, size=1000.0),) if ask is not None else ()
    return OrderBookSnapshot(token_id="t", bids=bids, asks=asks, fetched_at=_NOW)


def _symmetric_book(price: float | None) -> OrderBookSnapshot:
    """A zero-spread book (bid == ask) -- its midpoint equals the ask
    exactly, so these fixtures exercise the same boundary as a plain
    ask-threshold check would, while still going through the real
    midpoint-based code path."""
    return _book(bid=price, ask=price)


# --- A: there is no time-remaining restriction any more --------------------
# the signal is a pure function of the two order books -- it never looks
# at time at all, whether the market just opened or is about to close.

def test_a_the_function_never_looks_at_time_its_a_pure_book_function():
    result = assess_simple_entry(yes_order_book=_symmetric_book(0.80), no_order_book=_symmetric_book(0.10))
    assert result.outcome == "YES"


# --- B: implied probability (midpoint), not the raw ask, is the trigger ---

def test_b_a_070_midpoint_with_a_different_ask_still_qualifies_yes():
    # The governing worked example: bid 0.65 / ask 0.75 -> midpoint 0.70.
    book = _book(bid=0.65, ask=0.75)
    result = assess_simple_entry(yes_order_book=book, no_order_book=_symmetric_book(0.10))
    assert result.market_midpoint == pytest.approx(0.70)
    assert result.yes_implied_probability == pytest.approx(0.70)
    assert result.outcome == "YES"


def test_b2_execution_price_is_the_real_ask_not_the_implied_probability():
    book = _book(bid=0.65, ask=0.75)
    result = assess_simple_entry(yes_order_book=book, no_order_book=_symmetric_book(0.10))
    assert result.yes_implied_probability == pytest.approx(0.70)
    assert result.executable_entry_price == pytest.approx(0.75)  # the real ask, NOT 0.70


def test_b3_probability_can_be_070_even_when_ask_is_nowhere_near_070():
    # bid 0.60 / ask 0.80 -> midpoint 0.70 too, with an ask far from it.
    book = _book(bid=0.60, ask=0.80)
    result = assess_simple_entry(yes_order_book=book, no_order_book=_symmetric_book(0.10))
    assert result.yes_implied_probability == pytest.approx(0.70)
    assert result.outcome == "YES"
    assert result.executable_entry_price == pytest.approx(0.80)


# --- C: YES midpoint boundary ----------------------------------------------

def test_c_yes_midpoint_exactly_070_is_a_yes_candidate():
    result = assess_simple_entry(yes_order_book=_symmetric_book(0.70), no_order_book=_symmetric_book(0.10))
    assert result.outcome == "YES"


def test_c2_yes_midpoint_069_is_no_entry():
    result = assess_simple_entry(yes_order_book=_symmetric_book(0.69), no_order_book=_symmetric_book(0.10))
    assert result.outcome is None


# --- D: NO midpoint boundary (NO's own book, independently) ---------------

def test_d_no_midpoint_exactly_070_is_a_no_candidate():
    result = assess_simple_entry(yes_order_book=_symmetric_book(0.10), no_order_book=_symmetric_book(0.70))
    assert result.outcome == "NO"


def test_d2_no_midpoint_069_is_no_entry():
    result = assess_simple_entry(yes_order_book=_symmetric_book(0.10), no_order_book=_symmetric_book(0.69))
    assert result.outcome is None


# --- E: YES midpoint 0.70/0.30 selects the expected side -------------------
# (the two governing worked examples, read directly off market_midpoint)

def test_e_yes_midpoint_070_selects_yes():
    result = assess_simple_entry(yes_order_book=_book(bid=0.65, ask=0.75), no_order_book=_symmetric_book(0.10))
    assert result.market_midpoint == pytest.approx(0.70)
    assert result.outcome == "YES"


def test_e2_yes_midpoint_030_selects_no_via_no_implied_probability_070():
    # YES midpoint 0.30 -- NO's OWN book (independently, international-
    # style) must itself read ~0.70 for NO to qualify; this module never
    # computes no_implied_probability as `1 - yes_mid` itself.
    yes_book = _book(bid=0.25, ask=0.35)  # mid 0.30
    no_book = _book(bid=0.65, ask=0.75)  # mid 0.70, NO's OWN independent book
    result = assess_simple_entry(yes_order_book=yes_book, no_order_book=no_book)
    assert result.yes_implied_probability == pytest.approx(0.30)
    assert result.no_implied_probability == pytest.approx(0.70)
    assert result.outcome == "NO"
    assert result.executable_entry_price == pytest.approx(0.75)  # NO's own real ask


# --- F: both qualifying simultaneously is a conflicting/invalid setup -----

def test_f_both_yes_and_no_qualifying_is_no_trade():
    result = assess_simple_entry(yes_order_book=_symmetric_book(0.75), no_order_book=_symmetric_book(0.72))
    assert result.outcome is None
    assert "conflicting" in result.reason.lower()


# --- G: neither qualifying -------------------------------------------------

def test_g_neither_qualifying_is_no_trade():
    result = assess_simple_entry(yes_order_book=_symmetric_book(0.50), no_order_book=_symmetric_book(0.50))
    assert result.outcome is None


# --- H: missing book data is always HOLD, never a guess --------------------

def test_h_no_yes_order_book_at_all_is_no_trade():
    result = assess_simple_entry(yes_order_book=None, no_order_book=_symmetric_book(0.10))
    assert result.outcome is None
    assert result.yes_implied_probability is None


def test_h2_one_sided_book_with_no_bid_has_no_midpoint_so_no_trade():
    book = _book(bid=None, ask=0.90)  # ask-only -- mid is None, never guessed from ask alone
    result = assess_simple_entry(yes_order_book=book, no_order_book=_symmetric_book(0.10))
    assert result.market_midpoint is None
    assert result.yes_implied_probability is None
    assert result.outcome is None


# --- I: full logging vocabulary is always populated ------------------------

def test_i_signal_carries_every_required_logging_field():
    book = _book(bid=0.65, ask=0.75)
    result = assess_simple_entry(yes_order_book=book, no_order_book=_symmetric_book(0.10))
    assert result.yes_bid == pytest.approx(0.65)
    assert result.yes_ask == pytest.approx(0.75)
    assert result.market_midpoint == pytest.approx(0.70)
    assert result.yes_implied_probability == pytest.approx(0.70)
    assert result.no_implied_probability == pytest.approx(0.10)
    assert result.outcome == "YES"
    assert result.executable_entry_price == pytest.approx(0.75)


# --- J: default matches the governing spec ---------------------------------

def test_j_default_threshold_is_070():
    assert DEFAULT_ASK_THRESHOLD == pytest.approx(0.70)
