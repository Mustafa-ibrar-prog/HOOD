"""Focused tests for simple_entry_signal.py -- the ONLY production
entry-direction logic as of this round (a simple Polymarket-price
threshold, replacing Coinbase/Chainlink/confidence/historical
learning entirely for the live entry decision). Evaluated continuously
across the FULL 15-minute market -- there is no time-remaining
restriction. Pure-function tests against hand-built OrderBookSnapshot
values -- no run_cycle needed."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.polymarket.models import BookLevel, OrderBookSnapshot
from src.polymarket.simple_entry_signal import DEFAULT_ASK_THRESHOLD, assess_simple_entry

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _book(ask: float | None, bid: float | None = None) -> OrderBookSnapshot:
    asks = (BookLevel(price=ask, size=1000.0),) if ask is not None else ()
    bids = (BookLevel(price=bid, size=1000.0),) if bid is not None else ()
    return OrderBookSnapshot(token_id="t", bids=bids, asks=asks, fetched_at=_NOW)


# --- A: there is no time-remaining restriction any more --------------------
# the signal qualifies identically whether the market just opened (a full
# 15 minutes left) or is about to close -- the ONLY thing that matters is
# the real executable ask.

def test_a_qualifies_with_the_full_15_minutes_still_remaining():
    result = assess_simple_entry(yes_order_book=_book(0.80), no_order_book=_book(0.10))
    assert result.outcome == "YES"


def test_a2_qualifies_with_only_seconds_remaining_too():
    result = assess_simple_entry(yes_order_book=_book(0.80), no_order_book=_book(0.10))
    assert result.outcome == "YES"  # identical result -- this function never looks at time at all


# --- C: YES ask threshold boundary ----------------------------------------

def test_c_yes_ask_exactly_070_is_a_yes_candidate():
    result = assess_simple_entry(yes_order_book=_book(0.70), no_order_book=_book(0.10))
    assert result.outcome == "YES"


def test_c2_yes_ask_069_is_no_entry():
    result = assess_simple_entry(yes_order_book=_book(0.69), no_order_book=_book(0.10))
    assert result.outcome is None


# --- D: NO ask threshold boundary ------------------------------------------

def test_d_no_ask_exactly_070_is_a_no_candidate():
    result = assess_simple_entry(yes_order_book=_book(0.10), no_order_book=_book(0.70))
    assert result.outcome == "NO"


def test_d2_no_ask_069_is_no_entry():
    result = assess_simple_entry(yes_order_book=_book(0.10), no_order_book=_book(0.69))
    assert result.outcome is None


# --- E: both qualifying simultaneously is a conflicting/invalid setup -----

def test_e_both_yes_and_no_qualifying_is_no_trade():
    result = assess_simple_entry(yes_order_book=_book(0.75), no_order_book=_book(0.72))
    assert result.outcome is None
    assert "conflicting" in result.reason.lower()


# --- F: neither qualifying -------------------------------------------------

def test_f_neither_qualifying_is_no_trade():
    result = assess_simple_entry(yes_order_book=_book(0.50), no_order_book=_book(0.50))
    assert result.outcome is None


# --- G: the 70% condition uses the REAL executable ask, never a mid ------

def test_g_decision_uses_best_ask_not_mid():
    # A book whose mid would read >= 0.70 but whose best_ask does NOT.
    book = _book(ask=0.69, bid=0.60)  # mid = 0.645 -- but we care about best_ask only
    result = assess_simple_entry(yes_order_book=book, no_order_book=_book(0.10))
    assert result.outcome is None  # ask 0.69 doesn't qualify, regardless of what mid would say


def test_g2_missing_ask_side_never_qualifies():
    book = _book(ask=None, bid=0.90)  # no ask-side liquidity at all
    result = assess_simple_entry(yes_order_book=book, no_order_book=_book(0.10))
    assert result.outcome is None


# --- H: defaults match the governing spec ----------------------------------

def test_h_default_threshold_is_070():
    assert DEFAULT_ASK_THRESHOLD == pytest.approx(0.70)
