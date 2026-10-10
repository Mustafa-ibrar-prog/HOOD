"""Focused tests for simple_entry_signal.py -- the ONLY production
entry-direction logic as of this round (a simple Polymarket-price
threshold, replacing Coinbase/Chainlink/confidence/historical
learning entirely for the live entry decision). Pure-function tests
against hand-built OrderBookSnapshot values -- no run_cycle needed."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.polymarket.models import BookLevel, OrderBookSnapshot
from src.polymarket.simple_entry_signal import DEFAULT_ASK_THRESHOLD, DEFAULT_ENTRY_WINDOW_SECONDS, assess_simple_entry

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _book(ask: float | None, bid: float | None = None) -> OrderBookSnapshot:
    asks = (BookLevel(price=ask, size=1000.0),) if ask is not None else ()
    bids = (BookLevel(price=bid, size=1000.0),) if bid is not None else ()
    return OrderBookSnapshot(token_id="t", bids=bids, asks=asks, fetched_at=_NOW)


# --- A: more than 5 minutes remaining -> no entry evaluated at all --------

def test_a_more_than_five_minutes_remaining_is_not_eligible():
    result = assess_simple_entry(
        seconds_remaining=301.0, yes_order_book=_book(0.80), no_order_book=_book(0.10),
    )
    assert result.eligible is False
    assert result.outcome is None


def test_a2_unknown_remaining_time_is_treated_like_too_early():
    result = assess_simple_entry(seconds_remaining=None, yes_order_book=_book(0.80), no_order_book=_book(0.10))
    assert result.eligible is False
    assert result.outcome is None


# --- B: exactly 5 minutes remaining -> eligible ----------------------------

def test_b_exactly_five_minutes_remaining_is_eligible():
    result = assess_simple_entry(
        seconds_remaining=300.0, yes_order_book=_book(0.80), no_order_book=_book(0.10),
    )
    assert result.eligible is True
    assert result.outcome == "YES"


# --- C: YES ask threshold boundary ----------------------------------------

def test_c_yes_ask_exactly_070_is_a_yes_candidate():
    result = assess_simple_entry(seconds_remaining=100.0, yes_order_book=_book(0.70), no_order_book=_book(0.10))
    assert result.outcome == "YES"


def test_c2_yes_ask_069_is_no_entry():
    result = assess_simple_entry(seconds_remaining=100.0, yes_order_book=_book(0.69), no_order_book=_book(0.10))
    assert result.outcome is None
    assert result.eligible is True  # it WAS evaluated -- just didn't qualify


# --- D: NO ask threshold boundary ------------------------------------------

def test_d_no_ask_exactly_070_is_a_no_candidate():
    result = assess_simple_entry(seconds_remaining=100.0, yes_order_book=_book(0.10), no_order_book=_book(0.70))
    assert result.outcome == "NO"


def test_d2_no_ask_069_is_no_entry():
    result = assess_simple_entry(seconds_remaining=100.0, yes_order_book=_book(0.10), no_order_book=_book(0.69))
    assert result.outcome is None


# --- E: both qualifying simultaneously is a conflicting/invalid setup -----

def test_e_both_yes_and_no_qualifying_is_no_trade():
    result = assess_simple_entry(seconds_remaining=100.0, yes_order_book=_book(0.75), no_order_book=_book(0.72))
    assert result.outcome is None
    assert "conflicting" in result.reason.lower()


# --- F: neither qualifying -------------------------------------------------

def test_f_neither_qualifying_is_no_trade():
    result = assess_simple_entry(seconds_remaining=100.0, yes_order_book=_book(0.50), no_order_book=_book(0.50))
    assert result.outcome is None


# --- G: the 70% condition uses the REAL executable ask, never a mid ------

def test_g_decision_uses_best_ask_not_mid():
    # A book whose mid would read >= 0.70 but whose best_ask does NOT.
    book = _book(ask=0.69, bid=0.60)  # mid = 0.645 -- but we care about best_ask only
    result = assess_simple_entry(seconds_remaining=100.0, yes_order_book=book, no_order_book=_book(0.10))
    assert result.outcome is None  # ask 0.69 doesn't qualify, regardless of what mid would say


def test_g2_missing_ask_side_never_qualifies():
    book = _book(ask=None, bid=0.90)  # no ask-side liquidity at all
    result = assess_simple_entry(seconds_remaining=100.0, yes_order_book=book, no_order_book=_book(0.10))
    assert result.outcome is None


# --- H: defaults match the governing spec ----------------------------------

def test_h_defaults_are_300_seconds_and_070_threshold():
    assert DEFAULT_ENTRY_WINDOW_SECONDS == 300.0
    assert DEFAULT_ASK_THRESHOLD == pytest.approx(0.70)
