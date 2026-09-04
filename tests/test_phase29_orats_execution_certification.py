"""Phase 29, Part 5/17 — ORATS execution-realism grading: capped at B
(bid/ask+sizes only), never A, since no real trade-tick field exists."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.options.orats_execution_certification import build_orats_execution_realism_report
from src.options.orats_ingest import ingest_strike_rows
from src.options.phase26_execution_realism import ExecutionRealismGrade
from tests.orats_fixtures import SYNTHETIC_AAPL_STRIKES_20211201

RETRIEVAL = datetime(2026, 9, 4, tzinfo=timezone.utc)


def test_orats_contract_grades_b_never_a():
    store = ingest_strike_rows(SYNTHETIC_AAPL_STRIKES_20211201, retrieval_timestamp=RETRIEVAL, today=date(2026, 9, 4))
    cid = "AAPL_call_150.0000_2022-01-21"
    report = build_orats_execution_realism_report(store, cid)
    assert report.grade == ExecutionRealismGrade.B
    assert report.n_trades == 0


def test_orats_grade_computes_real_spread_stats():
    store = ingest_strike_rows(SYNTHETIC_AAPL_STRIKES_20211201, retrieval_timestamp=RETRIEVAL, today=date(2026, 9, 4))
    cid = "AAPL_call_150.0000_2022-01-21"
    report = build_orats_execution_realism_report(store, cid)
    assert report.mean_spread_dollars is not None
    assert report.mean_spread_dollars > 0
    assert report.quote_availability_rate == 1.0


def test_orats_grade_f_when_nothing_present():
    store = ingest_strike_rows(SYNTHETIC_AAPL_STRIKES_20211201, retrieval_timestamp=RETRIEVAL, today=date(2026, 9, 4))
    report = build_orats_execution_realism_report(store, "nonexistent_contract")
    assert report.grade == ExecutionRealismGrade.F


def test_downgrade_never_fires_on_a_report_that_was_never_a():
    """The downgrade logic must be a no-op for grades other than A --
    tested explicitly, not merely inferred from the B-only fixture
    above."""
    store = ingest_strike_rows(SYNTHETIC_AAPL_STRIKES_20211201, retrieval_timestamp=RETRIEVAL, today=date(2026, 9, 4))
    report = build_orats_execution_realism_report(store, "nonexistent_contract")
    assert report.grade == ExecutionRealismGrade.F  # unchanged, not silently bumped
