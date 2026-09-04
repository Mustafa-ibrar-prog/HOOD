"""Phase 33, Part D & I/24 — the p22_opt013_coarse_replication family."""

from __future__ import annotations

from pathlib import Path

from src.options.phase33_replication_hypotheses import (
    FAMILY,
    IS_PRIMARY_BY_ID,
    PRIMARY_HYPOTHESIS_ID,
    build_hypotheses,
    build_preregistrations,
    register_all,
)
from src.research.hypothesis import HypothesisRegistry
from src.research.preregistration import PreregistrationStore, require_preregistered


def test_five_hypotheses_one_feature_five_targets():
    hypotheses = build_hypotheses()
    assert len(hypotheses) == 5
    assert len({h.required_features[0] for h in hypotheses}) == 1
    assert len({h.target_definition for h in hypotheses}) == 5


def test_exactly_one_primary_hypothesis_is_the_mfe_target():
    hypotheses = build_hypotheses()
    primaries = [h for h in hypotheses if IS_PRIMARY_BY_ID[h.hypothesis_id]]
    assert len(primaries) == 1
    assert primaries[0].hypothesis_id == PRIMARY_HYPOTHESIS_ID
    assert primaries[0].target_definition == "forward_bucket_mfe_5"


def test_every_hypothesis_links_back_to_p22_opt_013():
    for h in build_hypotheses():
        assert h.parent_hypothesis_id == "P22-OPT-013"


def test_secondary_hypotheses_do_not_claim_a_borrowed_direction():
    """Only the MFE (and its mirrored spread target) may claim a
    directional prior -- Phase 22/23 never established one for MAE/ABS/DIR."""
    for h in build_hypotheses():
        if h.hypothesis_id in ("P33-REPL-MAE", "P33-REPL-ABS", "P33-REPL-DIR"):
            assert h.expected_direction == "unsigned"


def test_ids_unique_and_family_distinct_from_phase31_and_32():
    hypotheses = build_hypotheses()
    ids = [h.hypothesis_id for h in hypotheses]
    assert len(set(ids)) == 5
    assert all(hid.startswith("P33-REPL-") for hid in ids)
    assert all(h.family == FAMILY for h in hypotheses)
    assert FAMILY not in ("options_alpha_round2", "bucketed_options_alpha")


def test_register_all_persists_and_is_idempotent(tmp_path: Path):
    registry = HypothesisRegistry(tmp_path / "h.jsonl")
    prereg_store = PreregistrationStore(tmp_path / "p.jsonl")
    hypotheses = register_all(registry, prereg_store)
    assert len(registry.load_all()) == 5
    for h in hypotheses:
        require_preregistered(prereg_store, h.hypothesis_id, h.version)  # must not raise
    register_all(registry, prereg_store)
    assert len(registry.load_all()) == 5


def test_preregistrations_record_is_primary_flag():
    hypotheses = build_hypotheses()
    preregs = build_preregistrations(hypotheses)
    by_id = {p.hypothesis_id: p for p in preregs}
    assert by_id[PRIMARY_HYPOTHESIS_ID].parameter_ranges["is_primary"] is True
    assert by_id["P33-REPL-MAE"].parameter_ranges["is_primary"] is False
