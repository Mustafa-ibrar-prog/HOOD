"""Single-order-book market support -- Polymarket US's BTC Up/Down
contract has exactly ONE tradeable market per window, with ONE order
book (bids/offers), priced entirely on the YES/long axis. Direction is
expressed as BUY_LONG ("YES") vs BUY_SHORT ("NO") on that SAME
contract, never as two independent ERC-1155 tokens each with their own
book (that is international Polymarket's model -- see client.py and
models.OrderBookSnapshot's own docstring, which documents exactly that
assumption and is correct there).

us_client.py's `_to_binary_market` already reflects this structurally:
`token_id_yes == token_id_no == market_slug` for this venue (there is
only one slug to fetch a book for). Before this module existed,
engine.py fetched `client.get_order_book(market.token_id_yes)` and
`client.get_order_book(market.token_id_no)` as two SEPARATE calls --
on this venue those are the SAME call, returning the SAME data twice,
which is exactly the bug report this module fixes: identical
YES_ASK/NO_ASK readings in the logs were never two real, independent
prices -- they were one real book read twice and misinterpreted as
two.

`is_single_book_market()` detects this structurally (token_id_yes ==
token_id_no is true ONLY for this venue -- international's two token
ids are always genuinely distinct ERC-1155 token ids, confirmed in
client.py's `_to_binary_market`, which reads them from
`market.outcomes.yes.token_id`/`market.outcomes.no.token_id`, two
independently-assigned SDK fields that are never equal in practice).
`to_no_perspective()` derives the NO side's own economically-correct
view of that SAME single book, by inversion-and-complement -- it is
never a second, independently-fetched book, and the two returned
books (the real one and its derived complement) can never spuriously
both read as qualifying the SAME threshold, because their midpoints
always sum to exactly 1.0 by construction (see its own docstring)."""

from __future__ import annotations

from datetime import datetime, timezone

from src.polymarket.models import BinaryMarket, BookLevel, OrderBookSnapshot


def is_single_book_market(market: BinaryMarket) -> bool:
    """True only for a venue (Polymarket US, as of this writing) whose
    BinaryMarket was built with token_id_yes == token_id_no -- there is
    only one order book for the whole market, and direction is
    expressed via order intent (BUY_LONG/BUY_SHORT), never via two
    separate token ids. False for international Polymarket, whose two
    token ids are always genuinely distinct."""
    return market.token_id_yes == market.token_id_no


def to_no_perspective(order_book: OrderBookSnapshot) -> OrderBookSnapshot:
    """Derives the NO HOLDER's own view of a single YES-axis order book
    -- never a second, independently-fetched book (there isn't one on
    this venue). Economically:

      - Acquiring NO (BUY_SHORT) means disposing of YES exposure, which
        matches against the book's existing YES BIDS (the same way
        SELL_LONG would). The best (cheapest) price a NO buyer can get
        is therefore `1 - yes_best_bid` -- this becomes the derived
        book's best ASK (NO's own "best_ask", i.e. the real executable
        entry price for a NO buy).
      - Closing/covering a NO holding (SELL_SHORT) means re-acquiring
        YES exposure, which matches against the book's existing YES
        ASKS (the same way BUY_LONG would). The price a NO holder could
        exit at right now is therefore `1 - yes_best_ask` -- this
        becomes the derived book's best BID (the real executable exit
        price for closing a NO position, e.g. take_profit.py's
        check).

    So: derived.bids = sorted([(1 - ask.price, ask.size) for ask in
    order_book.asks], best-first = highest price first); derived.asks =
    sorted([(1 - bid.price, bid.size) for bid in order_book.bids],
    best-first = lowest price first).

    Because every price is a strict `1 - x` of the source book, the
    derived book's own midpoint is always EXACTLY `1 - order_book.mid`
    -- the two can never spuriously both read as qualifying the same
    probability threshold the way reading the SAME book twice did (see
    module docstring): yes_mid + no_mid == 1.0 always, by construction,
    not by coincidence.

    An empty/one-sided source book produces an equally empty/one-sided
    result on the opposite side (e.g. no bids on the source means no
    derived asks) -- never fabricated liquidity."""
    derived_bids = tuple(
        sorted(
            (BookLevel(price=round(1 - level.price, 4), size=level.size) for level in order_book.asks),
            key=lambda lvl: lvl.price, reverse=True,
        )
    )
    derived_asks = tuple(
        sorted(
            (BookLevel(price=round(1 - level.price, 4), size=level.size) for level in order_book.bids),
            key=lambda lvl: lvl.price,
        )
    )
    return OrderBookSnapshot(
        token_id=order_book.token_id, bids=derived_bids, asks=derived_asks,
        fetched_at=order_book.fetched_at or datetime.now(timezone.utc),
    )
