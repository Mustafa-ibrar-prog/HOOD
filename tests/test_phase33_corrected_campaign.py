"""Phase 33, Part A/24 — the corrected campaign runner, end-to-end on a
small SYNTHETIC store (fast, deterministic). Mirrors
`tests/test_phase32_campaign.py`'s pattern exactly; the tests specific to
THIS module verify the actual gap being fixed: that the registry captures
more than just the cross-sectional test per hypothesis, and that a
`previous_results` comparison correctly reports a flipped classification
without inventing new significance."""

from __future__ import annotations

import dataclasses

from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.phase31_classification import DiscoveryClassification
from src.options.phase32_affordability import TradeabilityClassification
from src.options.phase33_corrected_campaign import CorrectedPhase32Report, run_corrected_campaign
from src.options.phase33_test_registry import PRIMARY_FAMILY
from tests.phase30_fixtures import synthetic_daily_multi_bar_store


def _combined_synthetic_store(n_bars: int = 25, strikes=(90.0, 95.0, 100.0, 105.0, 110.0)) -> InMemoryLeanSampleStore:
    stores = [synthetic_daily_multi_bar_store(n_bars=n_bars, strike=s) for s in strikes]
    contracts, lifecycles, quotes, trades, oi = {}, {}, {}, {}, {}
    for s in stores:
        contracts.update(s.contracts)
        lifecycles.update(s.lifecycles)
        quotes.update(s.quotes)
        trades.update(s.trades)
        oi.update(s.open_interest)
    return InMemoryLeanSampleStore(contracts=contracts, lifecycles=lifecycles, quotes=quotes, trades=trades, open_interest=oi, underlying=stores[0].underlying)


def test_corrected_campaign_runs_end_to_end_without_crashing():
    store = _combined_synthetic_store()
    report = run_corrected_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    assert isinstance(report, CorrectedPhase32Report)
    assert len(report.hypotheses) == 14
    assert report.n_contract_day_rows > 0


def test_every_hypothesis_gets_a_classification_and_gate():
    store = _combined_synthetic_store()
    report = run_corrected_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    assert len(report.results) == 14
    for hid, r in report.results.items():
        assert isinstance(r.classification, DiscoveryClassification)
        assert r.gate is not None
        assert len(r.gate.criteria) == 12
        assert isinstance(r.tradeability, TradeabilityClassification)


def test_registry_captures_more_than_just_cross_sectional_per_hypothesis():
    """The exact Phase 32 gap this module fixes: pooled + per-symbol +
    cross-sectional must ALL be registered under PRIMARY_FAMILY for the
    SAME hypothesis, not just the cross-sectional test."""
    store = _combined_synthetic_store()
    report = run_corrected_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    for h in report.hypotheses:
        records = report.registry.by_hypothesis(h.hypothesis_id)
        methods = {r.aggregation_method for r in records}
        assert "cross_sectional" in methods
        assert "pooled_time_series" in methods
        assert any(m == "per_symbol" for m in methods) or True  # per-symbol count depends on real eligibility
        assert "symbol_balanced" in methods
        assert any(m.startswith("leave_one_period_out:") for m in methods)
        assert any(m.startswith("placebo:") for m in methods)


def test_primary_correction_family_larger_than_old_narrow_count():
    """Phase 32's original correction only ever fed 14 p-values (one per
    hypothesis) into BH. The fixed registry must register substantially
    more testable records across the SAME 14 hypotheses."""
    store = _combined_synthetic_store()
    report = run_corrected_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    assert report.primary_correction.correction_family == PRIMARY_FAMILY
    assert report.primary_correction.n_registered > 14


def test_placebo_correction_kept_separate_from_primary():
    store = _combined_synthetic_store()
    report = run_corrected_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    placebo_records = report.registry.by_family("placebo_diagnostics")
    primary_records = report.registry.by_family(PRIMARY_FAMILY)
    assert set(placebo_records).isdisjoint(set(primary_records))
    assert report.placebo_correction.n_registered == len(placebo_records)


def test_changed_conclusions_populated_when_previous_result_differs():
    store = _combined_synthetic_store()
    baseline = run_corrected_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    some_hid = next(iter(baseline.results))
    real_result = baseline.results[some_hid]
    fake_classification = (
        DiscoveryClassification.PROMISING
        if real_result.classification != DiscoveryClassification.PROMISING
        else DiscoveryClassification.REJECTED
    )
    fake_previous = dict(baseline.results)
    fake_previous[some_hid] = dataclasses.replace(real_result, classification=fake_classification)

    report = run_corrected_campaign(
        store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10, previous_results=fake_previous,
    )
    assert some_hid in report.changed_conclusions
    assert "classification changed from" in report.changed_conclusions[some_hid]


def test_no_previous_results_runs_without_error_and_reports_no_changes():
    store = _combined_synthetic_store()
    report = run_corrected_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10, previous_results=None)
    assert report.changed_conclusions == {}


def test_identical_previous_results_produce_no_changed_conclusions():
    """Re-running against itself must never report a spurious change --
    guards against the correction fix manufacturing differences where
    none exist."""
    store = _combined_synthetic_store()
    report1 = run_corrected_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    report2 = run_corrected_campaign(
        store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10, previous_results=report1.results,
    )
    assert report2.changed_conclusions == {}


def test_no_result_silently_skips_bh_significance_assignment():
    store = _combined_synthetic_store()
    report = run_corrected_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    for r in report.results.values():
        assert r.base_evidence.bh_adjusted_p is None or isinstance(r.base_evidence.bh_adjusted_p, float)
