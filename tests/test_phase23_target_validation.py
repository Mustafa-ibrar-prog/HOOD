"""Phase 23, Part 5/26 — 'exact MFE reproduction' and 'alternative
target alignment': the target-validation family's shape is exactly what
was preregistered, and Phase 23's re-derived mfe_5 matches Phase 22's
stored mfe_5 exactly for every (contract, date) row -- not just at
script-runtime (phase23_step0 already asserts this and refuses to
proceed on any mismatch), but as an independently pytest-checkable fact.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PHASE22_PANEL = REPO_ROOT / "logs" / "research_data" / "phase22_research_panel.jsonl"
PHASE23_PANEL = REPO_ROOT / "logs" / "research_data" / "phase23_research_panel.jsonl"


def _load_step2_module():
    path = REPO_ROOT / "scripts" / "phase23_step2_preregister_investigation.py"
    spec = importlib.util.spec_from_file_location("phase23_step2_preregister_investigation", path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO_ROOT))
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def step2():
    return _load_step2_module()


def test_target_validation_family_has_exactly_targets_a_through_j(step2):
    letters = [letter for letter, _col, _desc in step2.TARGET_VALIDATION_FAMILY]
    assert letters == ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]


def test_target_validation_family_target_f_is_the_frozen_parent_target(step2):
    by_letter = {letter: col for letter, col, _desc in step2.TARGET_VALIDATION_FAMILY}
    assert by_letter["F"] == "mfe_5"  # must exactly match P22-OPT-013's own target_definition


def test_target_validation_family_covers_every_required_forward_horizon(step2):
    by_letter = {letter: col for letter, col, _desc in step2.TARGET_VALIDATION_FAMILY}
    assert by_letter["A"] == "forward_return_1"
    assert by_letter["B"] == "forward_return_3"
    assert by_letter["C"] == "forward_return_5"
    assert by_letter["D"] == "forward_return_10"
    assert by_letter["E"] == "forward_return_20"


def test_control_hierarchy_has_exactly_ten_controls_in_fixed_order(step2):
    assert len(step2.CONTROL_HIERARCHY) == 10
    names = [name for name, _col in step2.CONTROL_HIERARCHY]
    expected_order = [f"control_{i}_" for i in range(1, 11)]
    for name, prefix in zip(names, expected_order):
        assert name.startswith(prefix), f"{name!r} is out of the fixed cumulative order (expected prefix {prefix!r})"


def test_tradeable_grid_matches_preregistration(step2):
    assert step2.THRESHOLD_GRID == (1.25, 1.50, 1.75, 2.00, 2.50)
    assert step2.HOLDING_PERIOD_GRID == (1, 3, 5, 10)
    assert len(step2.THRESHOLD_GRID) * len(step2.HOLDING_PERIOD_GRID) == 20  # "tightly bounded" -- Part 7


@pytest.mark.skipif(not PHASE22_PANEL.is_file() or not PHASE23_PANEL.is_file(), reason="research panels not present in this environment")
def test_phase23_mfe_5_matches_phase22_mfe_5_exactly_for_every_row():
    phase22_rows = {(r["option_id"], r["timestamp"]): r.get("mfe_5") for r in (json.loads(line) for line in PHASE22_PANEL.read_text().splitlines() if line.strip())}
    phase23_rows = [json.loads(line) for line in PHASE23_PANEL.read_text().splitlines() if line.strip()]
    assert len(phase23_rows) == len(phase22_rows)
    mismatches = 0
    for r in phase23_rows:
        key = (r["option_id"], r["timestamp"])
        original = phase22_rows.get(key)
        reproduced = r.get("mfe_5")
        if original is None and reproduced is None:
            continue
        if original is None or reproduced is None or abs(original - reproduced) > 1e-9:
            mismatches += 1
    assert mismatches == 0
