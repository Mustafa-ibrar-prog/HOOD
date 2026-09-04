"""Phase 29, Part 8/17 — re-testing the AAPL corporate-action question
against ORATS's schema."""

from __future__ import annotations

from src.options.orats_corporate_actions import (
    ORATS_CORPORATE_ACTION_COMPARISON,
    ORATS_CORPORATE_ACTION_ROOT_CAUSE,
    find_split_boundary_discontinuities,
)
from src.options.phase27_corporate_actions import CorporateActionRootCause


def test_root_cause_is_missing_adjustment_metadata_only():
    """ORATS's real /splits endpoint narrows Phase 27's two-part root
    cause (SOURCE_LIMITATION + MISSING_ADJUSTMENT_METADATA) down to just
    the metadata gap -- the endpoint itself is not a source limitation."""
    assert ORATS_CORPORATE_ACTION_ROOT_CAUSE == (CorporateActionRootCause.MISSING_ADJUSTMENT_METADATA,)
    assert CorporateActionRootCause.SOURCE_LIMITATION not in ORATS_CORPORATE_ACTION_ROOT_CAUSE


def test_comparison_mentions_the_real_splits_endpoint():
    text = ORATS_CORPORATE_ACTION_COMPARISON.lower()
    assert "/splits" in text
    assert "stocksplithistory" in text.replace("_", "").lower()


def test_comparison_is_honest_about_never_being_verified_live():
    text = ORATS_CORPORATE_ACTION_COMPARISON
    assert "ORATS_ACTIVATION_PENDING_HUMAN" in text
    assert "never verified against real" in text.lower()


def test_detector_is_reused_unchanged_from_phase27():
    """A direct re-import, not a re-implementation."""
    import src.options.phase27_corporate_actions as p27
    assert find_split_boundary_discontinuities is p27.find_split_boundary_discontinuities
