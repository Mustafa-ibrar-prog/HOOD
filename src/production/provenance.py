"""Phase 36, Part 7 — data provenance for every production feature.

A live decision must never silently treat a reconstructed-from-history
number as if it were a live observation, and must never accept a
feature the strategy declares REQUIRED when that feature is only
available as HISTORICAL/RECONSTRUCTED at decision time. This module is
the single place that rule is enforced, reused everywhere a production
feature is produced or consumed (LiveMarketSnapshot fields, a
strategy's `features` dict on its Decision, an Opportunity's inputs).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence


class DataProvenance(str, Enum):
    LIVE = "LIVE"  # observed directly from a live HOOD MCP tool call this cycle
    HISTORICAL = "HISTORICAL"  # sourced from a historical dataset (e.g. a research backtest), never live
    RECONSTRUCTED = "RECONSTRUCTED"  # derived from historical data to approximate a live feature (Phase 35's DATA_LIMITED discipline)
    DERIVED = "DERIVED"  # computed locally from other LIVE inputs this cycle (e.g. RSI from live bars) -- not itself a raw observation, but not stale/historical either


@dataclass(frozen=True)
class ProvenancedFeature:
    name: str
    value: Any
    provenance: DataProvenance
    required: bool  # does the strategy declare it cannot function without this feature?


class HistoricalFeatureRequiredLiveError(RuntimeError):
    """Raised when a REQUIRED feature is only available as HISTORICAL or
    RECONSTRUCTED at decision time -- Part 7: 'a feature marked
    HISTORICAL_ONLY must not be accepted unless the strategy explicitly
    does not require it.'"""


def assert_feature_acceptable_for_live_decision(feature: ProvenancedFeature) -> None:
    if feature.required and feature.provenance in (DataProvenance.HISTORICAL, DataProvenance.RECONSTRUCTED):
        raise HistoricalFeatureRequiredLiveError(
            f"Feature {feature.name!r} is required but only available as "
            f"{feature.provenance.value} at decision time -- refusing to feed a "
            "live decision a feature that cannot actually be observed live."
        )


def unacceptable_features(features: Sequence[ProvenancedFeature]) -> tuple[ProvenancedFeature, ...]:
    """Non-raising variant: returns every feature that WOULD fail the
    assertion above, so a caller can report all violations at once rather
    than stopping at the first one."""
    return tuple(
        f for f in features
        if f.required and f.provenance in (DataProvenance.HISTORICAL, DataProvenance.RECONSTRUCTED)
    )


def assert_reconstructed_never_masquerades_as_live(feature: ProvenancedFeature, *, claimed_provenance: DataProvenance) -> None:
    """Part 7: 'A RECONSTRUCTED historical feature must never masquerade
    as a live observation.' Guards against a caller relabeling a
    RECONSTRUCTED feature as LIVE when assembling a snapshot -- pass the
    feature's true, original provenance and the provenance a caller is
    about to claim for it; raises if they disagree in the unsafe
    direction (claiming LIVE for something that is really
    RECONSTRUCTED/HISTORICAL)."""
    if feature.provenance in (DataProvenance.RECONSTRUCTED, DataProvenance.HISTORICAL) and claimed_provenance == DataProvenance.LIVE:
        raise HistoricalFeatureRequiredLiveError(
            f"Feature {feature.name!r} is {feature.provenance.value} and cannot be relabeled LIVE."
        )
