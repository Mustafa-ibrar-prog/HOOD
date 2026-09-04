"""Phase 32, Parts 1 & 7/21 — bucketed_options_alpha hypothesis family
and minimum-sample requirements."""

from __future__ import annotations

from pathlib import Path

from src.options.phase32_hypotheses import (
    FAMILY,
    MIN_SAMPLE,
    build_hypotheses,
    build_preregistrations,
    hypothesis_id,
    register_all,
)
from src.research.hypothesis import HypothesisRegistry
from src.research.preregistration import PreregistrationStore, require_preregistered


def test_fourteen_hypotheses_registered():
    assert len(build_hypotheses()) == 14


def test_all_ids_unique_and_new_family_not_reused_from_phase31():
    hypotheses = build_hypotheses()
    ids = [h.hypothesis_id for h in hypotheses]
    assert len(set(ids)) == 14
    assert all(hid.startswith("P32-BKT-") for hid in ids)
    assert all(h.family == FAMILY for h in hypotheses)
    assert FAMILY != "options_alpha_round2"


def test_no_hypothesis_id_collides_with_phase31():
    from src.options.phase31_hypotheses import build_hypotheses as build_p31
    p31_ids = {h.hypothesis_id for h in build_p31()}
    p32_ids = {h.hypothesis_id for h in build_hypotheses()}
    assert p31_ids.isdisjoint(p32_ids)


def test_every_hypothesis_valid_direction_and_horizon():
    for h in build_hypotheses():
        assert h.expected_direction in ("positive", "negative", "unsigned")
        assert h.prediction_horizon_bars >= 1


def test_every_hypothesis_distinct_feature_target_pair():
    pairs = [(h.required_features[0], h.target_definition) for h in build_hypotheses()]
    assert len(set(pairs)) == 14


def test_min_sample_requirements_fixed_before_evaluation():
    assert MIN_SAMPLE.min_bucket_contracts == 3
    assert MIN_SAMPLE.min_bucket_series_dates == 10
    assert MIN_SAMPLE.min_symbol_level_observations == 15
    assert MIN_SAMPLE.min_pooled_observations == 30
    assert MIN_SAMPLE.min_cross_sectional_peer_group == 3


def test_preregistrations_carry_min_sample_requirements():
    hypotheses = build_hypotheses()
    preregs = build_preregistrations(hypotheses)
    for p in preregs:
        assert p.parameter_ranges["min_sample"]["min_bucket_contracts"] == MIN_SAMPLE.min_bucket_contracts


def test_register_all_persists_and_is_idempotent(tmp_path: Path):
    registry = HypothesisRegistry(tmp_path / "h.jsonl")
    prereg_store = PreregistrationStore(tmp_path / "p.jsonl")
    hypotheses = register_all(registry, prereg_store)
    assert len(registry.load_all()) == 14
    for h in hypotheses:
        require_preregistered(prereg_store, h.hypothesis_id, h.version)  # must not raise
    register_all(registry, prereg_store)  # re-run must not raise or duplicate
    assert len(registry.load_all()) == 14


def test_covers_all_five_feature_families():
    """Every one of Part 4's A-E families is represented by at least one hypothesis."""
    feature_cols = {h.required_features[0] for h in build_hypotheses()}
    assert "bucket_median_return" in feature_cols  # A
    assert "call_put_return_spread" in feature_cols  # B
    assert "otm_atm_spread" in feature_cols  # C
    assert "dte_slope" in feature_cols  # D
    assert "option_minus_underlying_return" in feature_cols  # E


def test_both_directional_and_non_directional_targets_present():
    targets = {h.target_definition for h in build_hypotheses()}
    assert any(t.startswith("forward_bucket_return") for t in targets)  # directional
    assert any(t.startswith("forward_dispersion") or t.startswith("forward_abs") or "mfe" in t for t in targets)  # non-directional
