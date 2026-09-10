"""Phase 42 — deterministic near-the-money strike targeting for Robinhood
option-instrument acquisition.

Context (Phase 41 cycle 2's real, observed failure): a broad
`get_option_instruments(chain_id=..., expiration_dates=..., state=...,
tradability=...)` query with NO strike filter returns pages in strike
order starting from the LOWEST strike in the chain. For a liquid,
high-priced underlying (QQQ ~$709, TSLA ~$364, ...) a single page — or
even several — can fail to reach the current price at all, and blind
`cursor`-pagination to get there is expensive (each page is a real,
sizeable HOOD tool call).

`HoodMarketDataProvider._fetch_all_instruments` (src/market/hood_provider.py,
UNMODIFIED by this phase) already implements real, bounded cursor
pagination (`_MAX_INSTRUMENT_PAGES = 25`) for when a broad scan is what's
wanted, and `src.live_bridge.merge_option_instrument_pages` (Phase 39,
UNMODIFIED) already handles merging multiple real agent-fetched pages
into one recordable file. Both remain available and untouched.

This module instead targets the problem at its root: `get_option_
instruments` accepts an EXACT `strike_price` filter (verified live,
Phase 41 cycle 3) that returns just the ~2 rows (one call, one put) at
that strike — no pagination needed at all. `compute_target_strikes`
computes a small, deterministic, BOUNDED set of exact strikes to query
directly, centered on the real current price, covering the same
moneyness band `src.research_recorder.contract_selection.
ContractSelectionBounds` will later filter down to anyway — so the agent
(Process A) fetches close to exactly what will be kept, never wastes a
call on a page that might not even reach the current price, and never
needs unbounded pagination to get there.

This computes WHICH STRIKES TO ASK FOR, never a contract's actual
data — every field of every instrument/quote returned by Robinhood is
still exactly what the real API responds with; a target strike that
doesn't exist as a real contract simply yields zero rows for that
request, never a fabricated one.
"""

from __future__ import annotations

from dataclasses import dataclass

# A generic, publicly documented options strike-increment convention
# (denser increments for lower-priced underlyings, coarser for
# higher-priced ones) -- used ONLY to pick which exact strikes are worth
# asking Robinhood about. It is a REQUEST heuristic, never a source of
# market data: if a guessed strike does not exist as a real, tradable
# contract, the real API simply returns nothing for it (see module
# docstring). Callers who already know a chain's real increment (e.g.
# observed from a prior get_option_instruments response this same cycle)
# should pass `strike_increment` explicitly instead of relying on this.
_DEFAULT_INCREMENT_BANDS: tuple[tuple[float, float], ...] = (
    (25.0, 1.0),
    (100.0, 2.5),
    (500.0, 5.0),
    (float("inf"), 10.0),
)


def infer_common_strike_increment(underlying_price: float) -> float:
    """A DEFAULT, overridable guess at this underlying's real strike
    increment, purely for deciding what to ask for -- see module
    docstring. Never treated as authoritative market data."""
    if underlying_price <= 0:
        raise ValueError("underlying_price must be > 0")
    for ceiling, increment in _DEFAULT_INCREMENT_BANDS:
        if underlying_price < ceiling:
            return increment
    return _DEFAULT_INCREMENT_BANDS[-1][1]


@dataclass(frozen=True)
class TargetStrikePlan:
    underlying_price: float
    strike_increment: float
    moneyness_band: float
    strikes: tuple[float, ...]  # ascending, deterministic, bounded by max_strikes


def compute_target_strikes(
    underlying_price: float,
    *,
    strike_increment: float | None = None,
    moneyness_band: float = 0.20,
    max_strikes: int = 6,
) -> TargetStrikePlan:
    """Deterministic, bounded list of exact strikes to query via
    `get_option_instruments(..., strike_price=<value>)`, centered on
    `underlying_price` and covering `moneyness_band` on each side (the
    SAME default band `ContractSelectionBounds.moneyness_band` uses, so
    acquisition targets what analysis will keep). Never unbounded:
    `max_strikes` caps the result (Phase 42's 'safety limit' requirement),
    trimmed symmetrically around the nearest-the-money strike first.
    """
    if underlying_price <= 0:
        raise ValueError("underlying_price must be > 0")
    if moneyness_band <= 0:
        raise ValueError("moneyness_band must be > 0")
    if max_strikes < 1:
        raise ValueError("max_strikes must be >= 1")

    increment = strike_increment if strike_increment is not None else infer_common_strike_increment(underlying_price)
    if increment <= 0:
        raise ValueError("strike_increment must be > 0")

    nearest = round(underlying_price / increment) * increment
    low_bound = underlying_price * (1.0 - moneyness_band)
    high_bound = underlying_price * (1.0 + moneyness_band)

    # Walk outward from the nearest-the-money strike alternating sides,
    # so trimming to max_strikes always keeps the closest strikes first.
    candidates: list[float] = [nearest]
    offset = 1
    while len(candidates) < max_strikes * 4:  # generous internal ceiling; final list is capped below
        added_any = False
        for sign in (1, -1):
            strike = round(nearest + sign * offset * increment, 4)
            if strike <= 0:
                continue
            if low_bound <= strike <= high_bound:
                candidates.append(strike)
                added_any = True
        offset += 1
        if not added_any and offset > 2:
            break

    # Order by distance from underlying_price (closest first), cap, then
    # present ascending for a stable, readable plan.
    candidates = sorted(set(candidates), key=lambda s: abs(s - underlying_price))[:max_strikes]
    strikes = tuple(sorted(candidates))

    return TargetStrikePlan(
        underlying_price=underlying_price, strike_increment=increment, moneyness_band=moneyness_band, strikes=strikes,
    )
