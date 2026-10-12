"""Divergence check between Coinbase (the existing live market-momentum
signal) and a settlement-aligned REFERENCE feed -- the actual source
the traded market resolves against.

RESEARCH FINDING (this session): Polymarket's own rule text for the
15-minute BTC Up/Down markets cites Chainlink's BTC/USD Data Stream
(https://data.chain.link/streams/btc-usd) as the resolution source --
NOT CF Benchmarks' BRTI, which CF Benchmarks' own site lists as used
by Kalshi/CME Group/ForecastEX, not Polymarket. This module is written
generically as "the reference feed" rather than hardcoding a provider
name, since the comparison logic below doesn't care which one
ultimately supplies the data.

LEGITIMATE ACCESS: Chainlink Data Streams (the specific feed Polymarket
cites) is a PAID subscription product -- credentials are issued only
after payment via app.chain.link; there is no free, public,
unauthenticated endpoint for it. Per explicit instruction, this module
never scrapes an undocumented endpoint or invents a substitute feed.
`btc_market_data.DirectBtcQuoteSource` (reused unmodified -- see that
module) is the exact Protocol a LICENSED Chainlink Data Streams client
plugs into later, the same way CoinbaseBtcQuoteSource already
implements it for the live-signal side. No concrete implementation of
it exists for the reference side yet. Until one is wired in (see
settings.reference_feed_enabled, default False), `assess_divergence()`
below always degrades to REFERENCE_UNAVAILABLE / zero penalty --
TODAY's live trading decision is governed by Coinbase ALONE, byte for
byte identical to before this module existed.

REUSE, NOT A SECOND SCORING ENGINE: whenever a reference feed IS
configured, its own direction is computed by calling
btc_entry_signal.assess_btc_entry_direction() UNMODIFIED on the
reference feed's own bars -- the IDENTICAL RSI/MACD/EMA/momentum
pipeline and the identical staleness/insufficiency gates Coinbase
already uses, never a second, independently-tuned indicator engine.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.polymarket.btc_entry_signal import BtcDirectionalAssessment

STATUS_AGREEMENT = "AGREEMENT"
STATUS_DIVERGENCE = "DIVERGENCE"
STATUS_REFERENCE_NEUTRAL = "REFERENCE_NEUTRAL"
STATUS_REFERENCE_UNAVAILABLE = "REFERENCE_UNAVAILABLE"
STATUS_REFERENCE_STALE = "REFERENCE_STALE"


@dataclass(frozen=True)
class DivergenceAssessment:
    status: str  # one of the STATUS_* constants above
    confidence_penalty: float  # always <= 0 -- this module only ever DECREASES confidence, never increases it
    reason: str


def assess_divergence(
    coinbase: BtcDirectionalAssessment,
    reference: BtcDirectionalAssessment | None,
    *,
    divergence_penalty: float,
) -> DivergenceAssessment:
    """`coinbase` is assumed already directional (never "neutral") --
    engine.py only ever reaches this call after its own neutral-
    direction early return, so there is deliberately no special case
    for a neutral `coinbase` here.

    `reference` is None whenever no reference feed is configured at
    all (today's default -- see module docstring). A configured feed
    instead always produces a real BtcDirectionalAssessment, which may
    itself read direction="neutral" from insufficient reference bars
    -- assess_btc_entry_direction() already turns a STALE or
    UNAVAILABLE reference feed into direction="neutral" via its own
    feed_status gate, so a bare `reference.feed_status.status` check
    still distinguishes "no opinion because thin data" (STALE/
    UNAVAILABLE, reported as such) from "no opinion because the
    evidence is genuinely non-directional" (REFERENCE_NEUTRAL)."""
    if reference is None:
        return DivergenceAssessment(STATUS_REFERENCE_UNAVAILABLE, 0.0, "no reference feed configured")
    if reference.feed_status.status == "UNAVAILABLE":
        return DivergenceAssessment(STATUS_REFERENCE_UNAVAILABLE, 0.0, "reference feed has no usable bars yet")
    if reference.feed_status.status == "STALE":
        return DivergenceAssessment(
            STATUS_REFERENCE_STALE, 0.0, "reference feed is stale -- cannot confirm or deny agreement with Coinbase",
        )
    if reference.direction == "neutral":
        return DivergenceAssessment(
            STATUS_REFERENCE_NEUTRAL, 0.0,
            "reference feed has no directional view this cycle -- neither confirming nor contradicting Coinbase",
        )
    if reference.direction == coinbase.direction:
        return DivergenceAssessment(STATUS_AGREEMENT, 0.0, f"reference feed agrees with Coinbase ({reference.direction})")
    return DivergenceAssessment(
        STATUS_DIVERGENCE, -abs(divergence_penalty),
        f"reference feed reads {reference.direction} while Coinbase reads {coinbase.direction} -- material disagreement",
    )
