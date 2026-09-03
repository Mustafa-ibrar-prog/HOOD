"""Phase 18, Part 14 — option-specific liquidity architecture.

Architecture only -- no thresholds are chosen here (Part 14: "This phase
should define the architecture, not optimize the thresholds"). Every
measurement is computed only from fields the chain observation actually
has OBSERVED; a metric whose inputs are UNAVAILABLE returns None rather
than a fabricated number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.options.chain import OptionChainObservation, OptionsFieldStatus


@dataclass(frozen=True)
class LiquidityMetrics:
    bid_ask_spread: float | None  # DERIVED: ask - bid, only when both OBSERVED
    spread_pct: float | None  # DERIVED: spread / midpoint, only when both OBSERVED
    volume: int | None  # pass-through of the observation's own OBSERVED/UNAVAILABLE volume
    open_interest: int | None  # pass-through
    quote_age_seconds: float | None  # DERIVED: (as_of - observation_timestamp), only when as_of is supplied

    @property
    def has_tradeable_quote(self) -> bool:
        """True only when a real bid AND ask were both observed -- never
        inferred from `last` alone (a stale last-trade price is not the
        same as a live two-sided market)."""
        return self.bid_ask_spread is not None


def compute_liquidity_metrics(observation: OptionChainObservation, *, as_of: datetime | None = None) -> LiquidityMetrics:
    spread = None
    spread_pct = None
    if observation.status_of("bid") == OptionsFieldStatus.OBSERVED and observation.status_of("ask") == OptionsFieldStatus.OBSERVED:
        if observation.bid is not None and observation.ask is not None:
            spread = observation.ask - observation.bid
            mid = observation.midpoint
            if mid is not None and mid > 0:
                spread_pct = spread / mid

    quote_age = None
    if as_of is not None:
        quote_age = (as_of - observation.observation_timestamp).total_seconds()

    volume = observation.volume if observation.status_of("volume") == OptionsFieldStatus.OBSERVED else None
    open_interest = observation.open_interest if observation.status_of("open_interest") == OptionsFieldStatus.OBSERVED else None

    return LiquidityMetrics(
        bid_ask_spread=spread, spread_pct=spread_pct, volume=volume, open_interest=open_interest, quote_age_seconds=quote_age,
    )
