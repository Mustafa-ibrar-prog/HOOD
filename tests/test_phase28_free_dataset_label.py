"""Phase 28, Part 15/17 — free dataset preservation label."""

from __future__ import annotations

from pathlib import Path

from src.options.phase28_free_dataset_label import (
    FREE_REFERENCE_DATASET_SOURCES,
    FREE_REFERENCE_DATASET_USES,
    NEVER_SILENTLY_MERGE_WITH_PAID_DATA,
    DatasetRole,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_dataset_role_has_free_and_paid_values():
    assert {r.value for r in DatasetRole} == {"free_reference_dataset", "paid_research_dataset"}


def test_free_dataset_sources_reference_phase26_and_phase27():
    joined = " ".join(FREE_REFERENCE_DATASET_SOURCES)
    assert "phase26_raw" in joined
    assert "phase27_raw" in joined


def test_free_dataset_uses_include_the_required_categories():
    assert "PIT tests" in FREE_REFERENCE_DATASET_USES
    assert "certification tests" in FREE_REFERENCE_DATASET_USES
    assert "regression tests" in FREE_REFERENCE_DATASET_USES


def test_never_silently_merge_flag_is_true():
    assert NEVER_SILENTLY_MERGE_WITH_PAID_DATA is True


def test_phase26_and_phase27_source_modules_are_unmodified_this_phase():
    """Confirms the label is applied by reference only -- none of the
    real Phase 26/27 modules were touched this phase."""
    import subprocess
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    changed = result.stdout.splitlines()
    for path in changed:
        assert "phase26_" not in path, f"{path} was modified this phase -- Phase 26 must stay untouched"
        assert "phase27_" not in path, f"{path} was modified this phase -- Phase 27 must stay untouched"
