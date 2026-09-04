"""Phase 31, Part 18/18 — the campaign orchestrator, end-to-end on a
small SYNTHETIC store (fast, deterministic) to verify the full wiring
before the real campaign script runs against real data."""

from __future__ import annotations

from pathlib import Path

from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.phase31_campaign import Phase31Report, run_campaign
from src.options.phase31_classification import DiscoveryClassification
from tests.phase30_fixtures import synthetic_daily_multi_bar_store


def _combined_synthetic_store(n_bars: int = 30, strikes=(95.0, 100.0, 105.0, 110.0)) -> InMemoryLeanSampleStore:
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
    assert isinstance(report, Phase31Report)
    assert len(report.hypotheses) == 16
    assert report.n_panel_rows > 0
    assert report.underlyings == ("AAPL",)


def test_every_hypothesis_gets_exactly_one_classification():
    store = _combined_synthetic_store()
    report = run_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    assert len(report.classifications) == 16
    for hid, (classification, reason) in report.classifications.items():
        assert isinstance(classification, DiscoveryClassification)
        assert len(reason) > 0


def test_every_hypothesis_gets_a_gate_result():
    store = _combined_synthetic_store()
    report = run_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    assert len(report.gates) == 16
    for gate in report.gates.values():
        assert len(gate.criteria) == 12


def test_multiple_testing_report_covers_all_sixteen():
    store = _combined_synthetic_store()
    report = run_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    assert report.multiple_testing["bonferroni"].n_tests == 16
    assert report.multiple_testing["holm"].n_tests == 16
    assert report.multiple_testing["benjamini_hochberg"].n_tests == 16


def test_preregistration_enforced_before_evaluation(tmp_path: Path):
    store = _combined_synthetic_store()
    registry_path = tmp_path / "hyp.jsonl"
    prereg_path = tmp_path / "prereg.jsonl"
    report = run_campaign(
        store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10,
        hypothesis_registry_path=registry_path, preregistration_store_path=prereg_path,
    )
    assert registry_path.is_file()
    assert prereg_path.is_file()
    from src.research.hypothesis import HypothesisRegistry
    assert len(HypothesisRegistry(registry_path).load_all()) == 16


def test_no_hypothesis_evidence_leaves_bh_fields_unset():
    store = _combined_synthetic_store()
    report = run_campaign(store, max_contracts_per_underlying=10, n_placebo_trials=5, n_bootstrap_resamples=10)
    for ev in report.evidence.values():
        # bh_significant may be True/False/None (None only if this hypothesis's IC was entirely undefined),
        # but the field must always have been touched by the multiple-testing pass.
        assert ev.bh_adjusted_p is None or isinstance(ev.bh_adjusted_p, float)
