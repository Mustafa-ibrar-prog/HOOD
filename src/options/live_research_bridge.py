"""Phase 30, Part 12/17 — the live/research data-bridge design.

Two data worlds this codebase now has, and this module's entire job is
to keep them from ever being silently mixed:
  - LIVE: Robinhood-backed, current-instant data (the existing
    `mcp__HOOD__get_option_quotes`/`get_equity_quotes`/etc. tools this
    codebase's live scanner/orchestrator already call).
  - RESEARCH: `FREE_REFERENCE_DATASET` (Phase 26/27's real, certified
    QuantConnect/Lean sample) -- historical, PARTIAL coverage, permanent
    limitations per `free_dataset_limitations.py` (Part 11).

Reuses `phase27_coverage_report.TARGET_UNDERLYINGS` directly as the
12-symbol live target universe -- the same list this project has used
consistently since Phase 27, not a redeclared parallel one.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.options.phase27_coverage_report import TARGET_UNDERLYINGS

# Real, confirmed (Phase 27): of the 12 target underlyings, only these two
# have ANY real historical options data in the free dataset (and even
# then, coverage is sparse/out-of-window -- see free_dataset_limitations.py).
HISTORICALLY_COVERED_TARGET_UNDERLYINGS: tuple[str, ...] = ("AAPL", "SPY")


class DataOrigin(enum.Enum):
    LIVE = "live"
    RESEARCH = "research"


class SymbolResearchAvailability(enum.Enum):
    HAS_HISTORICAL_RESEARCH = "has_historical_research"
    LIVE_ONLY_NO_HISTORICAL_RESEARCH = "live_only_no_historical_research"


class MixedOriginError(ValueError):
    """Raised whenever code tries to treat LIVE and RESEARCH data points
    as one homogeneous series -- Part 12's explicit "never blindly
    merged" requirement, enforced structurally rather than left as a
    convention."""


@dataclass(frozen=True)
class LabeledDataPoint:
    """`payload` is deliberately untyped (`Any`) -- it holds either a
    live quote/bar shape or a `ResearchObservation`, and `origin` is what
    a caller MUST check before assuming which. This module never
    interprets `payload`'s internal fields; it only ever labels and
    guards origin."""

    origin: DataOrigin
    symbol: str
    payload: Any
    retrieved_at: datetime


def label_live(symbol: str, payload: Any, *, retrieved_at: datetime) -> LabeledDataPoint:
    return LabeledDataPoint(origin=DataOrigin.LIVE, symbol=symbol, payload=payload, retrieved_at=retrieved_at)


def label_research(symbol: str, payload: Any, *, retrieved_at: datetime) -> LabeledDataPoint:
    return LabeledDataPoint(origin=DataOrigin.RESEARCH, symbol=symbol, payload=payload, retrieved_at=retrieved_at)


def assert_single_origin(points: list[LabeledDataPoint]) -> DataOrigin:
    """The one function every downstream consumer that wants to treat a
    batch of points as one series must call first. Raises
    `MixedOriginError` the instant a batch spans both LIVE and RESEARCH,
    and `ValueError` on an empty batch (never a silent default origin)."""
    if not points:
        raise ValueError("no points supplied -- cannot determine an origin for an empty batch")
    origins = {p.origin for p in points}
    if len(origins) > 1:
        raise MixedOriginError(
            f"points span multiple origins ({sorted(o.value for o in origins)}) -- LIVE and RESEARCH data "
            "must never be blindly merged into one series"
        )
    return origins.pop()


def research_availability_for_symbol(symbol: str) -> SymbolResearchAvailability:
    return (
        SymbolResearchAvailability.HAS_HISTORICAL_RESEARCH
        if symbol in HISTORICALLY_COVERED_TARGET_UNDERLYINGS
        else SymbolResearchAvailability.LIVE_ONLY_NO_HISTORICAL_RESEARCH
    )


@dataclass(frozen=True)
class LiveUniverseSymbolStatus:
    symbol: str
    research_availability: SymbolResearchAvailability
    live_visible: bool  # always True for every target-universe symbol -- research coverage never gates live visibility


def live_universe_status() -> tuple[LiveUniverseSymbolStatus, ...]:
    """Part 12's explicit requirement: 'the live scanner must be able to
    see all 12 target-universe symbols even where historical research
    doesn't cover them.' Every symbol in `TARGET_UNDERLYINGS` is always
    `live_visible=True`, regardless of `research_availability` -- a
    symbol's research gap never removes it from live consideration, it
    only labels the gap explicitly."""
    return tuple(
        LiveUniverseSymbolStatus(symbol=s, research_availability=research_availability_for_symbol(s), live_visible=True)
        for s in TARGET_UNDERLYINGS
    )
