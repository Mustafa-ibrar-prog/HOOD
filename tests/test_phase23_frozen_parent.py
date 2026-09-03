"""Phase 23, Part 2 — regression test proving the frozen P22-OPT-013
parent definition has not changed, and that the exact Phase 22 result
still reproduces from the exact Phase 22 panel/feature/target. If either
assertion ever fails, either P22-OPT-013 was edited (forbidden) or the
underlying computation changed silently (also a problem worth catching).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from src.research import HypothesisRegistry
from src.research.experiment_fingerprint import ExperimentDimensions, compute_experiment_fingerprint
from src.research.ic import compute_ic_series, summarize_ic
from src.research.stats_utils import t_test_p_value

REPO_ROOT = Path(__file__).resolve().parent.parent
HYPOTHESES_PATH = REPO_ROOT / "logs" / "research_data" / "hypotheses.jsonl"
PANEL_PATH = REPO_ROOT / "logs" / "research_data" / "phase22_research_panel.jsonl"

# Snapshot of the frozen definition, hard-coded here (not read from a mutable file this test also writes to) --
# this IS the regression guard: if P22-OPT-013's stored fields ever drift from these literal values, this test fails.
EXPECTED_FEATURE = ("option_range_expansion_5",)
EXPECTED_TARGET = "mfe_5"
EXPECTED_HORIZON = 5
EXPECTED_UNIVERSE = ("AAPL", "NVDA", "SPY", "TSLA", "QQQ", "MSFT", "AMD", "AMZN", "META", "GOOGL", "NFLX", "IWM")
EXPECTED_PARENT_HYPOTHESIS_ID = None
EXPECTED_FINGERPRINT = "c9226d827f192942bfc0186adb9f41a7c144c82ee4f09496980e7351fd8af55b"
EXPECTED_RESULT = {"pooled_ic": 0.09852, "p_value": 0.00001, "n": 7070}


def _load_parent():
    if not HYPOTHESES_PATH.is_file():
        pytest.skip("hypotheses.jsonl not present in this environment")
    registry = HypothesisRegistry(HYPOTHESES_PATH)
    hyp = registry.get("P22-OPT-013")
    if hyp is None:
        pytest.skip("P22-OPT-013 not registered in this environment")
    return hyp


def test_frozen_parent_feature_definition_unchanged():
    hyp = _load_parent()
    assert hyp.required_features == EXPECTED_FEATURE


def test_frozen_parent_target_definition_unchanged():
    hyp = _load_parent()
    assert hyp.target_definition == EXPECTED_TARGET


def test_frozen_parent_horizon_unchanged():
    hyp = _load_parent()
    assert hyp.prediction_horizon_bars == EXPECTED_HORIZON


def test_frozen_parent_universe_unchanged():
    hyp = _load_parent()
    assert tuple(hyp.universe) == EXPECTED_UNIVERSE


def test_frozen_parent_has_no_parent_hypothesis_id():
    """P22-OPT-013 is itself a top-level Phase 22 discovery -- it must
    never acquire a parent_hypothesis_id (that would mean something
    upstream silently reclassified it)."""
    hyp = _load_parent()
    assert hyp.parent_hypothesis_id == EXPECTED_PARENT_HYPOTHESIS_ID


def test_frozen_parent_fingerprint_reproduces_exactly():
    hyp = _load_parent()
    dims = ExperimentDimensions(
        feature_definition=str(hyp.required_features), parameter_range={"theme": "C", "horizon": hyp.prediction_horizon_bars},
        universe_name=str(hyp.universe), target_definition=hyp.target_definition, execution_model="n/a-discovery-only",
        cost_model="assumption-only-1x-2x-3x-5x", validation_methodology=hyp.test_methodology,
    )
    assert compute_experiment_fingerprint(dims) == EXPECTED_FINGERPRINT


def test_frozen_parent_result_reproduces_exactly_on_the_phase22_panel():
    hyp = _load_parent()
    if not PANEL_PATH.is_file():
        pytest.skip("phase22_research_panel.jsonl not present in this environment")
    rows = [json.loads(line) for line in PANEL_PATH.read_text().splitlines() if line.strip()]
    for r in rows:
        r["timestamp"] = date.fromisoformat(r["timestamp"])
    rows = [r for r in rows if r.get("is_research_eligible")]
    feature_col, target_col = hyp.required_features[0], hyp.target_definition
    eligible = [r for r in rows if r.get(feature_col) is not None and r.get(target_col) is not None]

    points = compute_ic_series(eligible, feature_col, target_col, min_universe_size=3)
    pooled_ic = summarize_ic(points, feature_name=feature_col, target_name=target_col).average_ic
    p_value = t_test_p_value([p.ic for p in points if p.ic is not None])

    assert pooled_ic == pytest.approx(EXPECTED_RESULT["pooled_ic"], abs=1e-4)
    assert p_value == pytest.approx(EXPECTED_RESULT["p_value"], abs=1e-4)
    assert len(eligible) == EXPECTED_RESULT["n"]
