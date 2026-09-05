"""Phase 37, Part 9 — live-recorder-only data provenance.

Deliberately a SEPARATE, narrower enum from
`src.production.provenance.DataProvenance` (which also has `HISTORICAL`/
`RECONSTRUCTED` — legitimate values for a research backtest, never for
what this package records). This phase's instruction is explicit: "Do
NOT use HISTORICAL / RECONSTRUCTED inside the live recorder unless
referring to metadata about a separate research dataset." Using the same
enum here would make it possible to accidentally tag a live observation
HISTORICAL/RECONSTRUCTED; a structurally smaller enum makes that
mistake unrepresentable, not merely disallowed by convention.
"""

from __future__ import annotations

from enum import Enum


class LiveObservationProvenance(str, Enum):
    LIVE = "LIVE"  # observed directly from a real HOOD MCP tool call this cycle
    DERIVED_FROM_LIVE = "DERIVED_FROM_LIVE"  # computed locally, this cycle, from LIVE inputs only (e.g. DTE, moneyness, mid-price)
    MISSING = "MISSING"  # the field was requested but not returned/parseable -- never filled, never carried forward
