"""Phase 29, Part 12/17 — ORATS coverage matrix: honest, currently all
NO_DATA, but the reporting machinery itself proven correct against a
synthetic populated fixture."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.options.orats_coverage_report import (
    CURRENT_ORATS_COVERAGE,
    TARGET_UNDERLYINGS,
    TARGET_YEARS,
    CoverageCell,
    build_orats_coverage_matrix,
)
from src.options.orats_ingest import ingest_strike_rows
from tests.orats_fixtures import SYNTHETIC_AAPL_STRIKES_20211201

RETRIEVAL = datetime(2026, 9, 4, tzinfo=timezone.utc)


def test_target_lists_match_phase27_exactly():
    assert TARGET_UNDERLYINGS == ("AAPL", "NVDA", "TSLA", "SPY", "QQQ", "MSFT", "AMD", "AMZN", "META", "GOOGL", "NFLX", "IWM")
    assert TARGET_YEARS == (2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026)


def test_current_real_coverage_is_entirely_no_data():
    """The honest, current state -- zero real ORATS observations."""
    assert CURRENT_ORATS_COVERAGE.any_real_data() is False
    for underlying in TARGET_UNDERLYINGS:
        for year in TARGET_YEARS:
            assert CURRENT_ORATS_COVERAGE.cell(underlying, year) == CoverageCell.NO_DATA


def test_matrix_machinery_correctly_marks_real_data_given_a_populated_store():
    """Proves the reporting code itself is correct, using a clearly-
    labeled synthetic fixture -- not a claim that real coverage exists."""
    store = ingest_strike_rows(SYNTHETIC_AAPL_STRIKES_20211201, retrieval_timestamp=RETRIEVAL, today=date(2026, 9, 4))
    matrix = build_orats_coverage_matrix(store)
    assert matrix.cell("AAPL", 2021) == CoverageCell.REAL_DATA
    assert matrix.cell("AAPL", 2020) == CoverageCell.NO_DATA
    assert matrix.any_real_data() is True


def test_never_credits_a_non_target_underlying_to_a_target_row():
    store = ingest_strike_rows(SYNTHETIC_AAPL_STRIKES_20211201, retrieval_timestamp=RETRIEVAL, today=date(2026, 9, 4))
    matrix = build_orats_coverage_matrix(store)
    # AAPL is a real target -- confirm nothing else was silently populated
    non_aapl_real = [(u, y) for u in TARGET_UNDERLYINGS if u != "AAPL" for y in TARGET_YEARS if matrix.cell(u, y) == CoverageCell.REAL_DATA]
    assert non_aapl_real == []


def test_no_cell_is_ever_partial_from_current_real_data():
    for cell in CURRENT_ORATS_COVERAGE.cells.values():
        assert cell != CoverageCell.PARTIAL
