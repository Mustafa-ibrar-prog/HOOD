"""Phase 29, Part 8 — re-testing the Phase 26 AAPL corporate-action
discontinuity against ORATS's (claimed) adjustment metadata.

Reuses Phase 27's real structural detector
(`phase27_corporate_actions.find_split_boundary_discontinuities`) --
it operates on the same shared `InMemoryLeanSampleStore` shape, so no
new detection logic is needed; this module adds only the ORATS-specific
comparison of what corporate-action metadata this provider's schema
actually offers.
"""

from __future__ import annotations

from src.options.phase27_corporate_actions import CorporateActionRootCause, find_split_boundary_discontinuities

# Re-exported for a single ORATS-scoped import point.
__all__ = ["find_split_boundary_discontinuities", "ORATS_CORPORATE_ACTION_COMPARISON", "ORATS_CORPORATE_ACTION_ROOT_CAUSE"]

# Real finding (Phase 25's schema evidence, re-confirmed this phase, no
# new probe): ORATS's schema has a DEDICATED, real `/splits` endpoint
# (StockSplitHistory: ticker/split_date/divisor) -- QuantConnect/Lean's
# options data has NO equivalent endpoint at all (Phase 26/27 had to
# INFER the AAPL 2014 split boundary purely from strike-value
# discontinuities, since no corporate-action feed existed for that
# source). This is real, incremental infrastructure ORATS offers that
# Lean does not. It does NOT, however, resolve the deeper gap: ORATS's
# Strike rows still have no explicit per-contract adjustment/adjusted-
# flag field joining a specific pre-split contract identity to its
# post-split successor -- so the SAME root cause Phase 27 found
# (SOURCE_LIMITATION + MISSING_ADJUSTMENT_METADATA) would still apply to
# ORATS's own Strike data, even with a real StockSplitHistory feed
# available to cross-reference against.
ORATS_CORPORATE_ACTION_ROOT_CAUSE = (CorporateActionRootCause.MISSING_ADJUSTMENT_METADATA,)

ORATS_CORPORATE_ACTION_COMPARISON = (
    "ORATS has a real, dedicated /splits endpoint (StockSplitHistory: ticker/split_date/divisor) that "
    "QuantConnect/Lean's options data entirely lacks -- a genuine, confirmed improvement in corporate-action "
    "INFRASTRUCTURE. However, ORATS's own Strike rows (the actual option contract data) have no confirmed "
    "adjusted-contract flag or explicit legacy/successor identity mapping, so a legacy contract still cannot "
    "be safely merged with a post-split contract using ORATS data alone -- a caller would need to cross-"
    "reference StockSplitHistory's split_date against each contract's own trade_date range manually, the same "
    "structural burden Phase 27's detector already handles generically (find_split_boundary_discontinuities), "
    "and the root cause narrows from Phase 27's two-part SOURCE_LIMITATION+MISSING_ADJUSTMENT_METADATA finding "
    "to just MISSING_ADJUSTMENT_METADATA (the /splits ENDPOINT itself is not a source limitation -- it exists "
    "and is real; the missing per-contract adjustment MAPPING is the remaining gap). Never verified against "
    "real ORATS AAPL 2014 data this phase -- no real API call was made (ORATS_ACTIVATION_PENDING_HUMAN)."
)
