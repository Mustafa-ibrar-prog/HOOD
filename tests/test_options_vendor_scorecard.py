"""Phase 24, Part 17 — the vendor scorecard: every row is well-formed,
honestly labeled about its own verification level, and no vendor claim
is silently presented as independently verified when it wasn't."""

from __future__ import annotations

from src.options.vendor_scorecard import (
    VENDOR_SCORECARD,
    OverallClassification,
    VerificationLevel,
    rows_by_classification,
)


def test_scorecard_has_at_least_ten_vendors():
    """Part 4 lists ~15 candidate sources; Part 17 asks for a scorecard
    covering 'every serious candidate' -- a meaningfully broad sweep,
    not a token 2-3 rows."""
    assert len(VENDOR_SCORECARD) >= 10


def test_every_row_has_a_verification_level():
    for row in VENDOR_SCORECARD:
        assert isinstance(row.verification_level, VerificationLevel)


def test_only_robinhood_is_marked_as_a_verified_real_probe():
    """No paid vendor was purchased or API-tested this phase (Part 19/
    20) -- every non-Robinhood row must honestly say so."""
    verified_sources = [r.source for r in VENDOR_SCORECARD if r.verification_level == VerificationLevel.VERIFIED_REAL_PROBE]
    assert len(verified_sources) == 1
    assert "robinhood" in verified_sources[0].lower()


def test_every_row_has_a_valid_overall_classification():
    for row in VENDOR_SCORECARD:
        assert isinstance(row.overall_classification, OverallClassification)


def test_every_row_has_all_required_columns_populated():
    required_text_fields = (
        "historical_depth", "daily_ohlc", "intraday", "bid_ask", "volume", "open_interest", "iv", "greeks",
        "expired_contracts", "historical_chain", "contract_lifecycle", "pit_capable", "api_access", "cost",
        "rate_limits", "licensing", "research_suitability", "notes",
    )
    for row in VENDOR_SCORECARD:
        for field_name in required_text_fields:
            value = getattr(row, field_name)
            assert isinstance(value, str) and len(value) > 0, f"{row.source}.{field_name} is empty"


def test_no_vendor_source_names_are_duplicated():
    sources = [row.source for row in VENDOR_SCORECARD]
    assert len(sources) == len(set(sources))


def test_rows_by_classification_covers_every_row_exactly_once():
    grouped = rows_by_classification()
    total = sum(len(v) for v in grouped.values())
    assert total == len(VENDOR_SCORECARD)


def test_no_unverified_row_claims_a_definitive_cost_without_hedging_language():
    """A row backed only by web research must not present a cost figure
    as flatly certain -- it should say 'reported'/'claimed'/'described'
    or similar, not assert it as this codebase's own verified fact."""
    hedge_words = ("report", "claim", "describ", "not itemized", "not published", "not found", "n/a")
    for row in VENDOR_SCORECARD:
        if row.verification_level != VerificationLevel.VENDOR_DOCUMENTATION_OR_THIRD_PARTY_SUMMARY:
            continue
        cost_lower = row.cost.lower()
        assert any(w in cost_lower for w in hedge_words), f"{row.source}'s cost field reads as unhedged fact: {row.cost!r}"


def test_at_least_one_vendor_flagged_for_a_marketing_claim_verification_gap():
    """Part 5's explicit instruction ('do not rely on marketing claims
    alone') must be operationalized somewhere in the scorecard, not just
    stated in a docstring."""
    assert any("marketing" in row.notes.lower() or "marketing" in row.research_suitability.lower() for row in VENDOR_SCORECARD)
