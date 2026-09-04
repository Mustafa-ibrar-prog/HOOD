"""Phase 30, Part 3/17 — the contract-selection engine."""

from __future__ import annotations

import dataclasses

from src.options.contract_selection import (
    RejectionReason,
    SelectionCriteria,
    SelectionDecision,
    eligible_rows,
    evaluate_contract,
    evaluate_contracts,
)
from src.options.research_dataset import build_research_observations
from tests.phase30_fixtures import synthetic_multi_bar_store, synthetic_store


def test_default_permissive_criteria_accepts_a_clean_row():
    store = synthetic_store()
    rows = build_research_observations(store)
    result = evaluate_contract(rows[0])
    assert result.decision == SelectionDecision.ELIGIBLE
    assert result.reasons == ()


def test_missing_bid_or_ask_rejected():
    store = synthetic_store()
    rows = build_research_observations(store)
    poisoned = dataclasses.replace(rows[0], bid=None)
    result = evaluate_contract(poisoned)
    assert result.decision == SelectionDecision.REJECTED
    assert RejectionReason.NO_BID in result.reasons


def test_wide_spread_rejected_when_criteria_tightened():
    store = synthetic_store()
    rows = build_research_observations(store)
    tight = SelectionCriteria(max_spread_pct=0.001)
    result = evaluate_contract(rows[0], tight)
    assert RejectionReason.WIDE_SPREAD in result.reasons


def test_insufficient_volume_and_oi():
    store = synthetic_multi_bar_store(n_bars=1)
    rows = build_research_observations(store)
    strict = SelectionCriteria(min_volume=1000.0, min_open_interest=1000.0)
    result = evaluate_contract(rows[0], strict)
    assert RejectionReason.INSUFFICIENT_VOLUME in result.reasons
    assert RejectionReason.INSUFFICIENT_OI in result.reasons


def test_missing_volume_is_insufficient_data_not_insufficient_volume():
    store = synthetic_store()
    rows = build_research_observations(store)
    # rows[1] (second timestamp) has no trade data at all in the base fixture.
    result = evaluate_contract(rows[1])
    assert RejectionReason.INSUFFICIENT_DATA in result.reasons
    assert RejectionReason.INSUFFICIENT_VOLUME not in result.reasons


def test_invalid_dte_rejected():
    store = synthetic_multi_bar_store(n_bars=1)
    rows = build_research_observations(store)
    narrow = SelectionCriteria(min_dte=0, max_dte=1)
    result = evaluate_contract(rows[0], narrow)
    assert RejectionReason.INVALID_DTE in result.reasons


def test_invalid_moneyness_rejected():
    store = synthetic_multi_bar_store(n_bars=1)
    rows = build_research_observations(store)
    narrow = SelectionCriteria(min_moneyness=0.999, max_moneyness=1.001)
    result = evaluate_contract(rows[0], narrow)
    assert RejectionReason.INVALID_MONEYNESS in result.reasons


def test_price_too_high_rejected():
    store = synthetic_multi_bar_store(n_bars=1)
    rows = build_research_observations(store)
    cheap_cap = SelectionCriteria(max_premium_per_contract_usd=1.0)
    result = evaluate_contract(rows[0], cheap_cap)
    assert RejectionReason.PRICE_TOO_HIGH in result.reasons


def test_data_quality_failure_rejected():
    store = synthetic_multi_bar_store(n_bars=1)
    rows = build_research_observations(store)
    from src.options.research_dataset import DataQualityStatus
    poisoned = dataclasses.replace(rows[0], data_quality=DataQualityStatus.FLAGGED_CRITICAL)
    result = evaluate_contract(poisoned)
    assert RejectionReason.DATA_QUALITY_FAILURE in result.reasons


def test_pit_failure_rejected_when_required():
    store = synthetic_multi_bar_store(n_bars=1)
    rows = build_research_observations(store)
    from src.options.research_dataset import PITStatus
    poisoned = dataclasses.replace(rows[0], pit_status=PITStatus.PIT_UNKNOWN)
    result = evaluate_contract(poisoned)
    assert RejectionReason.PIT_FAILURE in result.reasons
    lenient = SelectionCriteria(require_pit_safe=False)
    result2 = evaluate_contract(poisoned, lenient)
    assert RejectionReason.PIT_FAILURE not in result2.reasons


def test_eligible_rows_filters_correctly():
    store = synthetic_multi_bar_store(n_bars=5)
    rows = build_research_observations(store)
    results = evaluate_contracts(rows)
    n_eligible = sum(1 for r in results if r.is_eligible())
    filtered = eligible_rows(rows)
    assert len(filtered) == n_eligible


def test_multiple_reasons_can_accumulate():
    store = synthetic_multi_bar_store(n_bars=1)
    rows = build_research_observations(store)
    poisoned = dataclasses.replace(rows[0], bid=None, ask=None, volume=None, open_interest=None)
    result = evaluate_contract(poisoned)
    assert RejectionReason.NO_BID in result.reasons
    assert RejectionReason.NO_ASK in result.reasons
    assert RejectionReason.INSUFFICIENT_DATA in result.reasons
    assert len(result.reasons) >= 3
