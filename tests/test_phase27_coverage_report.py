"""Phase 27, Part 12/16 — coverage matrix and field-availability report,
built against a small constructed fixture store."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.data.source_profile import DataProvenance
from src.data.store_interfaces import ProvenancedObservation
from src.data.timestamp_model import EventTimestamps
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore, build_contract_identity, build_provenance
from src.options.phase26_lean_sample_parser import LeanContractFileMeta
from src.options.phase27_coverage_report import (
    TARGET_UNDERLYINGS,
    TARGET_YEARS,
    CoverageCell,
    build_coverage_matrix,
    build_field_availability_report,
    moneyness_bucket,
)

RETRIEVAL = datetime(2026, 9, 3, tzinfo=timezone.utc)


def _obs(key, field, value, ts):
    return ProvenancedObservation(key=key, field=field, value=value,
                                   timestamps=EventTimestamps(event_time=ts, observation_time=ts),
                                   provenance=DataProvenance.OBSERVED, source="test")


def test_target_underlyings_match_part_2s_exact_list():
    assert TARGET_UNDERLYINGS == ("AAPL", "NVDA", "TSLA", "SPY", "QQQ", "MSFT", "AMD", "AMZN", "META", "GOOGL", "NFLX", "IWM")


def test_target_years_span_2019_through_2026():
    assert TARGET_YEARS == (2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026)


def test_coverage_matrix_marks_a_real_year_as_real_data():
    p = build_provenance(retrieval_timestamp=RETRIEVAL, adjustment_status="x")
    meta = LeanContractFileMeta("SPY", "call", 430.0, date(2023, 9, 1), "quote", "american", None)
    c = build_contract_identity(meta, p)
    store = InMemoryLeanSampleStore(
        contracts={c.option_id: c}, lifecycles={},
        quotes={c.option_id: [_obs(c.option_id, "bid", 1.0, datetime(2023, 8, 3))]},
        trades={}, open_interest={}, underlying={},
    )
    matrix = build_coverage_matrix(store)
    assert matrix.cell("SPY", 2023) == CoverageCell.REAL_DATA
    assert matrix.cell("SPY", 2022) == CoverageCell.NO_DATA


def test_coverage_matrix_never_marks_a_non_target_underlying_year_as_real_for_a_target_row():
    """GOOG must never be credited to GOOGL's row."""
    p = build_provenance(retrieval_timestamp=RETRIEVAL, adjustment_status="x")
    meta = LeanContractFileMeta("GOOG", "call", 700.0, date(2015, 12, 24), "quote", "american", None)
    c = build_contract_identity(meta, p)
    store = InMemoryLeanSampleStore(
        contracts={c.option_id: c}, lifecycles={},
        quotes={c.option_id: [_obs(c.option_id, "bid", 1.0, datetime(2015, 12, 23))]},
        trades={}, open_interest={}, underlying={},
    )
    matrix = build_coverage_matrix(store)
    assert matrix.cell("GOOGL", 2015) == CoverageCell.NO_DATA
    assert ("GOOG", 2015) in matrix.bonus_coverage


def test_empty_store_is_all_no_data():
    store = InMemoryLeanSampleStore(contracts={}, lifecycles={}, quotes={}, trades={}, open_interest={}, underlying={})
    matrix = build_coverage_matrix(store)
    for u in TARGET_UNDERLYINGS:
        for y in TARGET_YEARS:
            assert matrix.cell(u, y) == CoverageCell.NO_DATA


def test_no_cell_is_ever_synthetic_only():
    """Part 12: never fill a gap with synthetic data -- this phase's
    matrix builder has no code path that can ever produce SYNTHETIC_ONLY."""
    store = InMemoryLeanSampleStore(contracts={}, lifecycles={}, quotes={}, trades={}, open_interest={}, underlying={})
    matrix = build_coverage_matrix(store)
    assert all(cell != CoverageCell.SYNTHETIC_ONLY for cell in matrix.cells.values())


def test_moneyness_bucket_classifies_near_atm_correctly():
    assert moneyness_bucket(100.0, [100.0]) == "0.98x-1.02x_near_atm"
    assert moneyness_bucket(50.0, [100.0]) == "deep_itm_or_otm_below_0.9x"
    assert moneyness_bucket(150.0, [100.0]) == "above_1.10x"


def test_moneyness_bucket_returns_unknown_with_no_underlying_price():
    assert moneyness_bucket(100.0, []) == "unknown_no_underlying_price"


def test_field_availability_report_counts_calls_and_puts_separately():
    p = build_provenance(retrieval_timestamp=RETRIEVAL, adjustment_status="x")
    meta_c = LeanContractFileMeta("AAPL", "call", 100.0, date(2016, 1, 15), "quote", "american", None)
    meta_p = LeanContractFileMeta("AAPL", "put", 100.0, date(2016, 1, 15), "quote", "american", None)
    c1, c2 = build_contract_identity(meta_c, p), build_contract_identity(meta_p, p)
    store = InMemoryLeanSampleStore(
        contracts={c1.option_id: c1, c2.option_id: c2}, lifecycles={},
        quotes={c1.option_id: [_obs(c1.option_id, "bid", 1.0, datetime(2015, 1, 2))]},
        trades={}, open_interest={}, underlying={},
    )
    rep = build_field_availability_report(store, "AAPL")
    assert rep.contract_count == 2
    assert rep.call_count == 1
    assert rep.put_count == 1
    assert rep.iv_available_native is False
    assert rep.greeks_available_native is False
