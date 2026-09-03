"""Phase 27, Part 8/16 — corporate-action investigation: the detector
correctly flags a real split-boundary discontinuity, never asserts an
unconfirmed successor mapping, and never merges two distinct contract
identities."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.data.source_profile import DataProvenance
from src.data.store_interfaces import ProvenancedObservation
from src.data.timestamp_model import EventTimestamps
from src.options.historical_data_interfaces import ContractLifecycle, ContractLifecycleStatus
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore, build_contract_identity, build_provenance
from src.options.phase26_lean_sample_parser import LeanContractFileMeta
from src.options.phase27_corporate_actions import (
    AAPL_2014_SPLIT_ROOT_CAUSE,
    CorporateActionRootCause,
    find_split_boundary_discontinuities,
)

RETRIEVAL = datetime(2026, 9, 3, tzinfo=timezone.utc)


def _contract_and_lifecycle(strike, expiration, first_obs, last_trade):
    p = build_provenance(retrieval_timestamp=RETRIEVAL, adjustment_status="x")
    meta = LeanContractFileMeta("SYNTH", "call", strike, expiration, "quote", "american", None)
    c = build_contract_identity(meta, p)
    lc = ContractLifecycle(c.option_id, first_obs, None, last_trade, expiration, ContractLifecycleStatus.EXPIRED, p)
    return c, lc


def test_root_cause_is_source_limitation_and_missing_metadata_never_a_codebase_bug():
    """Part 8's diagnostic requirement -- this must not be misattributed
    to a parser/identity/normalization bug in this codebase."""
    assert CorporateActionRootCause.SOURCE_LIMITATION in AAPL_2014_SPLIT_ROOT_CAUSE
    assert CorporateActionRootCause.MISSING_ADJUSTMENT_METADATA in AAPL_2014_SPLIT_ROOT_CAUSE
    assert CorporateActionRootCause.PARSER_ISSUE not in AAPL_2014_SPLIT_ROOT_CAUSE
    assert CorporateActionRootCause.CONTRACT_IDENTITY_ISSUE not in AAPL_2014_SPLIT_ROOT_CAUSE


def test_detects_a_legacy_contract_that_stops_before_the_boundary():
    c1, lc1 = _contract_and_lifecycle(700.0, date(2015, 1, 17), date(2014, 1, 2), date(2014, 6, 6))
    store = InMemoryLeanSampleStore(contracts={c1.option_id: c1}, lifecycles={c1.option_id: lc1},
                                     quotes={}, trades={}, open_interest={}, underlying={})
    flags = find_split_boundary_discontinuities(store, "SYNTH", date(2014, 6, 9))
    assert len(flags) == 1
    assert flags[0].legacy_strike == 700.0


def test_does_not_flag_a_contract_still_trading_through_the_boundary():
    c1, lc1 = _contract_and_lifecycle(100.0, date(2016, 1, 15), date(2014, 1, 2), date(2015, 6, 1))
    store = InMemoryLeanSampleStore(contracts={c1.option_id: c1}, lifecycles={c1.option_id: lc1},
                                     quotes={}, trades={}, open_interest={}, underlying={})
    flags = find_split_boundary_discontinuities(store, "SYNTH", date(2014, 6, 9))
    assert flags == ()


def test_never_asserts_a_successor_when_no_unambiguous_candidate_exists():
    """Part 8: 'a legacy contract must not be merged with a post-action
    contract unless identity rules prove they represent the same
    economic contract.' With zero candidates, successor_strike stays
    None -- nothing is asserted."""
    c1, lc1 = _contract_and_lifecycle(700.0, date(2015, 1, 17), date(2014, 1, 2), date(2014, 6, 6))
    store = InMemoryLeanSampleStore(contracts={c1.option_id: c1}, lifecycles={c1.option_id: lc1},
                                     quotes={}, trades={}, open_interest={}, underlying={})
    flags = find_split_boundary_discontinuities(store, "SYNTH", date(2014, 6, 9))
    assert flags[0].successor_strike is None


def test_reports_but_never_confirms_a_single_candidate_successor():
    """A single same-expiration/right candidate at a different strike
    starting on/after the boundary is REPORTED as a possibility, never
    silently treated as proven -- the flag's own note says UNCONFIRMED."""
    legacy, legacy_lc = _contract_and_lifecycle(700.0, date(2015, 1, 17), date(2014, 1, 2), date(2014, 6, 6))
    successor, successor_lc = _contract_and_lifecycle(100.0, date(2015, 1, 17), date(2014, 6, 9), date(2014, 12, 1))
    store = InMemoryLeanSampleStore(
        contracts={legacy.option_id: legacy, successor.option_id: successor},
        lifecycles={legacy.option_id: legacy_lc, successor.option_id: successor_lc},
        quotes={}, trades={}, open_interest={}, underlying={},
    )
    flags = find_split_boundary_discontinuities(store, "SYNTH", date(2014, 6, 9))
    legacy_flag = next(f for f in flags if f.legacy_strike == 700.0)
    assert legacy_flag.successor_strike == 100.0
    assert "UNCONFIRMED" in legacy_flag.note
    assert "not merged" in legacy_flag.note


def test_ambiguous_multiple_candidates_report_no_single_successor():
    legacy, legacy_lc = _contract_and_lifecycle(700.0, date(2015, 1, 17), date(2014, 1, 2), date(2014, 6, 6))
    succ_a, succ_a_lc = _contract_and_lifecycle(100.0, date(2015, 1, 17), date(2014, 6, 9), date(2014, 12, 1))
    succ_b, succ_b_lc = _contract_and_lifecycle(101.0, date(2015, 1, 17), date(2014, 6, 9), date(2014, 12, 1))
    store = InMemoryLeanSampleStore(
        contracts={legacy.option_id: legacy, succ_a.option_id: succ_a, succ_b.option_id: succ_b},
        lifecycles={legacy.option_id: legacy_lc, succ_a.option_id: succ_a_lc, succ_b.option_id: succ_b_lc},
        quotes={}, trades={}, open_interest={}, underlying={},
    )
    flags = find_split_boundary_discontinuities(store, "SYNTH", date(2014, 6, 9))
    legacy_flag = next(f for f in flags if f.legacy_strike == 700.0)
    assert legacy_flag.successor_strike is None
