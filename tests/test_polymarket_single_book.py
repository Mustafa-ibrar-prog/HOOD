"""Focused tests for single_book.py -- the fix for Polymarket US's
single-order-book market model (one real book, priced on the YES
axis; direction via BUY_LONG/BUY_SHORT, never two separate token
ids/books). These are the module the bug report's "identical
YES_ASK/NO_ASK" symptom traces back to: engine.py used to fetch
`client.get_order_book(token_id_yes)` and
`client.get_order_book(token_id_no)` as if they were two independent
calls -- on this venue token_id_yes == token_id_no, so both calls
returned the exact same data, misread as two real, independent
prices."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.polymarket.models import BinaryMarket, BookLevel, OrderBookSnapshot
from src.polymarket.single_book import is_single_book_market, to_no_perspective

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _market(**overrides) -> BinaryMarket:
    defaults = dict(
        condition_id="c1", question="Will BTC be up?", token_id_yes="slug-a", token_id_no="slug-a",
        close_time=_NOW, fetched_at=_NOW,
    )
    defaults.update(overrides)
    return BinaryMarket(**defaults)


def _book(bids: tuple[tuple[float, float], ...], asks: tuple[tuple[float, float], ...]) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        token_id="slug-a",
        bids=tuple(BookLevel(price=p, size=s) for p, s in bids),
        asks=tuple(BookLevel(price=p, size=s) for p, s in asks),
        fetched_at=_NOW,
    )


# --- A: single-book detection -----------------------------------------------

def test_a_identical_token_ids_is_a_single_book_market():
    assert is_single_book_market(_market(token_id_yes="slug-a", token_id_no="slug-a")) is True


def test_a2_distinct_token_ids_is_not_a_single_book_market():
    assert is_single_book_market(_market(token_id_yes="token-yes", token_id_no="token-no")) is False


# --- B: the core inversion -- worked examples from the governing spec ------

def test_b_yes_bid_027_gives_a_no_best_ask_of_073():
    # "YES bid = 0.27 -> NO implied ask = 0.73" -- the exact worked example.
    book = _book(bids=((0.27, 100.0),), asks=((0.74, 100.0),))
    no_view = to_no_perspective(book)
    assert no_view.best_ask == pytest.approx(0.73)


def test_b2_yes_ask_074_gives_a_no_best_bid_of_026():
    book = _book(bids=((0.27, 100.0),), asks=((0.74, 100.0),))
    no_view = to_no_perspective(book)
    assert no_view.best_bid == pytest.approx(0.26)


# --- C: midpoints are EXACT complements -- never spuriously both qualify --

def test_c_no_perspective_midpoint_is_exactly_one_minus_yes_midpoint():
    book = _book(bids=((0.65, 100.0),), asks=((0.75, 100.0),))  # yes mid = 0.70
    no_view = to_no_perspective(book)
    assert book.mid == pytest.approx(0.70)
    assert no_view.mid == pytest.approx(0.30)
    assert book.mid + no_view.mid == pytest.approx(1.0)


def test_c2_the_old_bug_cannot_recur_reading_the_same_book_twice_vs_deriving_it():
    """The bug this module fixes: fetching "the same book twice" (what
    engine.py used to do) gives IDENTICAL yes/no readings, which could
    spuriously both read as qualifying the same high threshold.
    Deriving NO's view via to_no_perspective() instead can NEVER do
    that -- the two midpoints always sum to exactly 1.0, so both can
    only read >= 0.70 if their sum is >= 1.4, which is impossible."""
    book = _book(bids=((0.88, 100.0),), asks=((0.88, 100.0),))  # the exact "0.88/0.88" bug-report reading
    # The OLD (buggy) behavior: read the SAME book as if it were NO's own.
    buggy_no_reading = book
    assert buggy_no_reading.mid == pytest.approx(0.88)  # would have falsely "qualified" NO too

    # The FIX: derive NO's real view instead.
    correct_no_view = to_no_perspective(book)
    assert correct_no_view.mid == pytest.approx(0.12)  # 1 - 0.88, correctly does NOT qualify
    assert correct_no_view.mid != book.mid


# --- D: best-first ordering is preserved on both derived sides ------------

def test_d_derived_bids_are_still_best_highest_first():
    book = _book(bids=(), asks=((0.60, 10.0), (0.70, 10.0), (0.80, 10.0)))
    no_view = to_no_perspective(book)
    # asks 0.60/0.70/0.80 -> derived bids 0.40/0.30/0.20, best (highest) first
    assert [lvl.price for lvl in no_view.bids] == [pytest.approx(0.40), pytest.approx(0.30), pytest.approx(0.20)]


def test_d2_derived_asks_are_still_best_lowest_first():
    book = _book(bids=((0.20, 10.0), (0.30, 10.0), (0.40, 10.0)), asks=())
    no_view = to_no_perspective(book)
    # bids 0.40/0.30/0.20 -> derived asks 0.60/0.70/0.80, best (lowest) first
    assert [lvl.price for lvl in no_view.asks] == [pytest.approx(0.60), pytest.approx(0.70), pytest.approx(0.80)]


# --- E: an empty/one-sided source book never fabricates liquidity ---------

def test_e_no_bids_at_all_means_no_derived_asks_at_all():
    book = _book(bids=(), asks=((0.75, 100.0),))
    no_view = to_no_perspective(book)
    assert no_view.asks == ()
    assert no_view.best_bid == pytest.approx(0.25)


def test_e2_no_asks_at_all_means_no_derived_bids_at_all():
    book = _book(bids=((0.25, 100.0),), asks=())
    no_view = to_no_perspective(book)
    assert no_view.bids == ()
    assert no_view.best_ask == pytest.approx(0.75)


def test_e3_a_fully_empty_book_derives_to_an_equally_empty_book():
    book = _book(bids=(), asks=())
    no_view = to_no_perspective(book)
    assert no_view.bids == () and no_view.asks == ()
    assert no_view.best_bid is None and no_view.best_ask is None


# --- F: share sizes are carried through unchanged --------------------------

def test_f_share_sizes_are_preserved_not_recomputed():
    book = _book(bids=((0.27, 42.0),), asks=((0.74, 17.0),))
    no_view = to_no_perspective(book)
    assert no_view.best_bid == pytest.approx(0.26)
    # derived asks come from the SOURCE bids (42.0 shares); derived bids
    # come from the SOURCE asks (17.0 shares) -- see to_no_perspective's
    # own docstring on which side maps to which.
    assert no_view.asks[0].size == pytest.approx(42.0)
    assert no_view.bids[0].size == pytest.approx(17.0)
