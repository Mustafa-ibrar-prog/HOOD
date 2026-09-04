"""Phase 30, Part 11/17 — the permanent free-data limitations registry."""

from __future__ import annotations

from src.options.free_dataset_limitations import (
    FREE_DATASET_LIMITATIONS,
    LimitationCategory,
    attach_limitations_disclosure,
    render_limitations_markdown,
)


def test_all_twelve_categories_present_exactly_once():
    categories = [r.category for r in FREE_DATASET_LIMITATIONS]
    assert len(categories) == len(LimitationCategory)
    assert set(categories) == set(LimitationCategory)


def test_every_record_is_permanent():
    assert all(r.permanent for r in FREE_DATASET_LIMITATIONS)


def test_every_record_cites_real_evidence():
    for r in FREE_DATASET_LIMITATIONS:
        assert len(r.evidence) > 10
        assert len(r.description) > 20


def test_render_markdown_mentions_every_category():
    md = render_limitations_markdown()
    for cat in LimitationCategory:
        assert cat.value in md


def test_attach_limitations_disclosure_always_carries_full_registry():
    wrapped = attach_limitations_disclosure("Some research report body.")
    assert wrapped.report_body == "Some research report body."
    assert wrapped.limitations == FREE_DATASET_LIMITATIONS
    assert len(wrapped.limitations) == 12


def test_missing_underlyings_record_names_the_real_gap():
    rec = next(r for r in FREE_DATASET_LIMITATIONS if r.category == LimitationCategory.MISSING_UNDERLYINGS)
    assert "NVDA" in rec.description and "AAPL" in rec.description


def test_no_native_iv_and_greeks_records_are_distinct():
    iv = next(r for r in FREE_DATASET_LIMITATIONS if r.category == LimitationCategory.NO_NATIVE_IV)
    greeks = next(r for r in FREE_DATASET_LIMITATIONS if r.category == LimitationCategory.NO_NATIVE_GREEKS)
    assert iv.description != greeks.description
