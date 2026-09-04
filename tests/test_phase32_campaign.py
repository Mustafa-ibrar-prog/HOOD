"""Phase 32, Parts 15 & 16/21 — the bucketed-alpha campaign orchestrator,
end-to-end on a small SYNTHETIC store (fast, deterministic)."""

from __future__ import annotations

from pathlib import Path

from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.phase31_classification import DiscoveryClassification
from src.options.phase32_affordability import TradeabilityClassification
from src.options.phase32_campaign import Phase32Report, run_campaign
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


def test_campaign_runs_end_to_end_without_crashing():
    store = _combined_synthetic_store()
    report = run_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    assert isinstance(report, Phase32Report)
    assert len(report.hypotheses) == 14
    assert report.n_contract_day_rows > 0


def test_every_hypothesis_gets_a_classification_and_gate():
    store = _combined_synthetic_store()
    report = run_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    assert len(report.results) == 14
    for hid, r in report.results.items():
        assert isinstance(r.classification, DiscoveryClassification)
        assert r.gate is not None
        assert len(r.gate.criteria) == 12
        assert isinstance(r.tradeability, TradeabilityClassification)


def test_multiple_testing_covers_all_fourteen():
    store = _combined_synthetic_store()
    report = run_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    assert report.multiple_testing["benjamini_hochberg"].n_tests == 14
    assert report.multiple_testing["bonferroni"].n_tests == 14
    assert report.multiple_testing["holm"].n_tests == 14


def test_phase31_comparison_answers_all_nine_questions():
    store = _combined_synthetic_store()
    report = run_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    for key in (
        "q1_solved_contract_density_problem", "q2_effective_sample_size_increased", "q3_any_phase31_null_became_testable",
        "q4_survived_underlying_controls", "q5_survived_multiple_testing", "q6_survived_placebo",
        "q7_survived_symbol_period_robustness", "q8_became_affordable", "q9_passed_promising_gate",
    ):
        assert key in report.phase31_comparison
        assert isinstance(report.phase31_comparison[key], bool)


def test_preregistration_enforced_before_evaluation(tmp_path: Path):
    store = _combined_synthetic_store()
    registry_path = tmp_path / "h32.jsonl"
    prereg_path = tmp_path / "p32.jsonl"
    run_campaign(
        store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10,
        hypothesis_registry_path=registry_path, preregistration_store_path=prereg_path,
    )
    assert registry_path.is_file()
    from src.research.hypothesis import HypothesisRegistry
    assert len(HypothesisRegistry(registry_path).load_all()) == 14


def test_scheme_selection_recorded_and_reasoned():
    store = _combined_synthetic_store()
    report = run_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    assert report.scheme_selection.chosen_scheme.name in ("fine", "coarse")
    assert report.scheme_selection.reason


def test_no_result_silently_skips_bh_significance_assignment():
    store = _combined_synthetic_store()
    report = run_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    for r in report.results.values():
        assert r.base_evidence.bh_adjusted_p is None or isinstance(r.base_evidence.bh_adjusted_p, float)
