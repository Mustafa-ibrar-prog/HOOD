"""Phase 7, Part 19 & 23: static safety checks — no live/paper orders
anywhere in Phase 7's code, no import of the live execution/orchestrator
path, and reproducibility of the deterministic (seeded) machinery."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE7_SRC_MODULES = [
    "stats_utils.py", "partition.py", "multiple_testing.py", "purged_cv.py", "hypothesis_similarity.py",
    "overfitting_metrics.py", "economic_significance.py", "cross_sectional_alpha.py", "alpha_decay.py",
    "cross_sectional_placebo.py", "hypothesis_generator.py", "preregistration.py", "baseline_comparison.py",
    "scorecard.py", "research_gate.py", "experiment_fingerprint.py", "research_family.py",
]
PHASE7_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase7_*.py"))

FORBIDDEN_IMPORT_PREFIXES = ("src.execution", "src.orchestrator")
FORBIDDEN_CALLS = ("place_equity_order", "place_option_order", "place_crypto_order", "submit_order", "cancel_equity_order", "cancel_option_order")


def _all_phase7_files():
    return [REPO_ROOT / "src" / "research" / name for name in PHASE7_SRC_MODULES] + list(PHASE7_SCRIPTS)


def test_no_phase7_module_imports_the_live_execution_or_orchestrator_path():
    for path in _all_phase7_files():
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in FORBIDDEN_IMPORT_PREFIXES:
                    assert not node.module.startswith(prefix), f"{path} imports {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in FORBIDDEN_IMPORT_PREFIXES:
                        assert not alias.name.startswith(prefix), f"{path} imports {alias.name}"


def test_no_phase7_module_references_a_live_order_placement_call():
    for path in _all_phase7_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_research_gate_module_cannot_grant_paper_or_live_trading():
    from src.research.research_gate import CODE_COMPUTABLE_STAGES, ResearchLifecycleStage

    assert ResearchLifecycleStage.PAPER_TRADING not in CODE_COMPUTABLE_STAGES
    assert ResearchLifecycleStage.LIVE_TRADING not in CODE_COMPUTABLE_STAGES


def test_scorecard_and_gate_modules_never_import_execution_gateway():
    """A second, independent check via actual import introspection (not
    just source-text scanning) — importing these modules must not pull in
    anything execution-related as a side effect."""
    import sys

    before = set(sys.modules.keys())
    import src.research.scorecard  # noqa: F401
    import src.research.research_gate  # noqa: F401
    after = set(sys.modules.keys())
    newly_imported = after - before
    assert not any(m.startswith("src.execution") or m.startswith("src.orchestrator") for m in newly_imported)


# --- reproducibility ---------------------------------------------------------------------


def test_multiple_testing_corrections_are_pure_functions_deterministic():
    from src.research.multiple_testing import benjamini_hochberg_fdr

    ps = [("a", 0.01), ("b", 0.2), ("c", 0.03)]
    r1 = benjamini_hochberg_fdr(ps)
    r2 = benjamini_hochberg_fdr(ps)
    assert r1.results == r2.results


def test_purged_cv_folds_are_deterministic_given_the_same_inputs():
    from datetime import datetime, timedelta, timezone

    from src.research.purged_cv import PurgedCVConfig, generate_purged_folds

    timestamps = [datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i) for i in range(100)]
    config = PurgedCVConfig(n_splits=5, prediction_horizon_bars=5, purge_window_bars=1, embargo_bars=2)
    f1 = generate_purged_folds(timestamps, config)
    f2 = generate_purged_folds(timestamps, config)
    assert f1 == f2


def test_hypothesis_generator_output_is_deterministic():
    """Every field except `created_at` (a real wall-clock timestamp,
    which correctly differs between two independent calls) must be
    byte-for-byte identical across two calls with the same universe."""
    from src.research.hypothesis_generator import generate_hypotheses

    a = generate_hypotheses(["AAPL", "MSFT"])
    b = generate_hypotheses(["AAPL", "MSFT"])
    for ha, hb in zip(a, b):
        da, db = ha.to_dict(), hb.to_dict()
        da.pop("created_at")
        db.pop("created_at")
        assert da == db
