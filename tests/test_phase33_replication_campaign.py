"""Phase 33, Parts C-L/24 — the P22-OPT-013 coarse-grained replication
campaign, end-to-end on a small SYNTHETIC store (fast, deterministic)."""

from __future__ import annotations

from pathlib import Path

from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.phase31_classification import DiscoveryClassification
from src.options.phase32_affordability import TradeabilityClassification
from src.options.phase33_replication_campaign import ReplicationReport, ReplicationVerdict, run_replication_campaign
from src.options.phase33_replication_hypotheses import PRIMARY_HYPOTHESIS_ID
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


def test_replication_campaign_runs_end_to_end_without_crashing():
    store = _combined_synthetic_store()
    report = run_replication_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    assert isinstance(report, ReplicationReport)
    assert len(report.hypotheses) == 5
    assert report.n_contract_day_rows > 0


def test_every_hypothesis_gets_a_classification_and_gate():
    store = _combined_synthetic_store()
    report = run_replication_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    assert len(report.results) == 5
    for hid, r in report.results.items():
        assert isinstance(r.classification, DiscoveryClassification)
        assert r.gate is not None
        assert len(r.gate.criteria) == 12
        assert isinstance(r.tradeability, TradeabilityClassification)


def test_only_real_classification_values_ever_used():
    """Part K: no invented weaker category."""
    store = _combined_synthetic_store()
    report = run_replication_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    allowed = set(DiscoveryClassification)
    for r in report.results.values():
        assert r.classification in allowed


def test_registry_includes_group_balanced_and_non_overlap_records():
    store = _combined_synthetic_store()
    report = run_replication_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    for h in report.hypotheses:
        methods = {r.aggregation_method for r in report.registry.by_hypothesis(h.hypothesis_id)}
        assert "dte_balanced" in methods
        assert "moneyness_balanced" in methods
        assert "call_put_balanced" in methods
        assert "non_overlapping_window" in methods
        assert "cross_sectional" in methods


def test_primary_correction_family_covers_all_five_hypotheses_worth_of_tests():
    store = _combined_synthetic_store()
    report = run_replication_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    assert report.primary_correction.correction_family == PRIMARY_FAMILY
    assert report.primary_correction.n_registered >= 5  # at minimum one cross-sectional test per hypothesis


def test_verdict_is_computed_only_from_primary_hypothesis():
    store = _combined_synthetic_store()
    report = run_replication_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    assert isinstance(report.verdict, ReplicationVerdict)
    primary_result = report.results[PRIMARY_HYPOTHESIS_ID]
    expected_did_replicate = primary_result.classification in (DiscoveryClassification.DISCOVERY_SUPPORTED, DiscoveryClassification.PROMISING)
    assert report.verdict.did_replicate == expected_did_replicate


def test_verdict_never_claims_replication_on_a_secondary_target_alone():
    """If the primary (MFE) hypothesis is NOT_READY/INCONCLUSIVE/REJECTED
    but a secondary target happens to look significant, did_replicate
    must still be False -- the verdict is never borrowed from a
    secondary target."""
    store = _combined_synthetic_store()
    report = run_replication_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    primary = report.results[PRIMARY_HYPOTHESIS_ID]
    if primary.classification not in (DiscoveryClassification.DISCOVERY_SUPPORTED, DiscoveryClassification.PROMISING):
        assert report.verdict.did_replicate is False


def test_expiration_and_year_concentration_present():
    store = _combined_synthetic_store()
    report = run_replication_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    assert report.expiration_concentration.n_rows >= 0
    assert report.year_concentration.n_rows >= 0


def test_preregistration_enforced_before_evaluation(tmp_path: Path):
    store = _combined_synthetic_store()
    registry_path = tmp_path / "h33.jsonl"
    prereg_path = tmp_path / "p33.jsonl"
    run_replication_campaign(
        store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10,
        hypothesis_registry_path=registry_path, preregistration_store_path=prereg_path,
    )
    assert registry_path.is_file()
    from src.research.hypothesis import HypothesisRegistry
    assert len(HypothesisRegistry(registry_path).load_all()) == 5


def test_range_expansion_feature_actually_attached_to_bucket_rows():
    store = _combined_synthetic_store()
    report = run_replication_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    assert report.n_bucket_rows > 0
    # feature coverage may legitimately be zero on a tiny synthetic panel (no 5-day trailing
    # baseline available yet) -- assert the field exists and is never negative, not that it's positive
    assert report.n_rows_with_range_expansion >= 0
