"""Phase 27 Final Safety Check (Part 15): historical options DATASET
EXPANSION only -- no alpha hypothesis, no signal search, no parameter
optimization, no strategy, no backtest, no order, no new live execution
path, no claimed alpha discovery, no vendor purchased, no fabricated
historical field, no synthetic data presented as real.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE27_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase27_*.py"))
PHASE27_SRC_MODULES = [
    "src/options/phase27_merge.py",
    "src/options/phase27_ingest.py",
    "src/options/phase27_corporate_actions.py",
    "src/options/phase27_coverage_report.py",
    "src/options/phase27_concentration.py",
    "src/options/phase27_dataset_manifest.py",
    "src/options/phase27_fingerprint.py",
    "src/options/phase27_certified_expanded_dataset.py",
    "src/options/phase27_provider_expansion.py",
]
FORBIDDEN_IMPORT_PREFIXES = ("src.execution.gateway", "src.execution.live_client", "src.orchestrator")
FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order", "submit_order",
    "cancel_equity_order", "cancel_option_order", "review_option_order", "review_equity_order",
)


def _all_phase27_files():
    return [REPO_ROOT / rel for rel in PHASE27_SRC_MODULES] + list(PHASE27_SCRIPTS)


def test_phase27_files_exist():
    for rel in PHASE27_SRC_MODULES:
        assert (REPO_ROOT / rel).is_file(), f"missing {rel}"
    assert len(PHASE27_SCRIPTS) >= 1


def test_no_phase27_file_imports_the_live_order_placement_path():
    for path in _all_phase27_files():
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


def test_no_phase27_file_references_a_live_or_paper_order_placement_call():
    for path in _all_phase27_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_no_phase27_file_creates_a_strategy_backtest_or_hypothesis():
    forbidden_patterns = (
        "LiveStrategy(", "PaperStrategy(", "StrategyExecutor(", "connect_alpha_to_execution",
        "Hypothesis(", "HypothesisRegistry(", "PreregistrationRecord(", "compute_ic_series(",
        "grid_search(", "optimize_parameters(", "run_backtest(", "sharpe_optimi", "signal_rank",
        "profitable_signal", "claimed_edge", "alpha_discovery",
    )
    for path in _all_phase27_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to register a hypothesis/backtest/strategy via {pattern!r}"


def test_no_phase27_file_touches_development_validation_or_final_holdout_data():
    for path in PHASE27_SCRIPTS:
        source = path.read_text()
        assert "PartitionLifecycleStage.VALIDATION" not in source
        assert "PartitionLifecycleStage.FINAL_HOLDOUT" not in source
        assert "PartitionLifecycleStage.DEVELOPMENT" not in source


def test_no_phase27_file_purchases_a_vendor_or_stores_a_real_api_key():
    forbidden_patterns = (
        "purchase(", "create_account(", "api_key=\"", "API_KEY=\"", "stripe.", "checkout.",
        "credit_card", "payment_method=",
    )
    for path in _all_phase27_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to purchase/store credentials for a vendor via {pattern!r}"


def test_no_live_or_paper_trading_enabled_by_this_phase():
    forbidden_patterns = ("live_trading_confirmed=True", "live_auto_execute=True", "trading_mode=\"live\"", "trading_mode='live'")
    for path in _all_phase27_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to enable live/paper trading via {pattern!r}"


def test_no_phase27_file_fabricates_a_historical_field():
    forbidden_patterns = (
        "fabricated_bid", "fabricated_ask", "fabricated_oi", "fabricated_iv", "fabricated_greeks",
        "assumed_historical_bid", "assumed_historical_ask", "synthetic_historical_quote",
        "reconstructed_and_presented_as_observed",
    )
    for path in _all_phase27_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate a historical field via {pattern!r}"


def test_synthetic_test_data_never_constructed_outside_test_files():
    """Part 4: REAL_EXTERNAL_DATA and SYNTHETIC_TEST_DATA must never be
    mixed -- src/ modules may DISCUSS the distinction (in docstrings,
    explaining why a mechanism is tested with synthetic fixtures in
    tests/) but must never literally construct a synthetic observation
    with a 'synthetic' source string as part of a real code path."""
    forbidden_constructions = ('source="synthetic', "source='synthetic", 'source="synthetic_test_source"')
    for path in [REPO_ROOT / rel for rel in PHASE27_SRC_MODULES]:
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_constructions:
            assert pattern not in source, f"{path} appears to construct a synthetic observation via {pattern!r}"


def test_coverage_matrix_module_never_emits_synthetic_only_from_real_code_paths():
    src = (REPO_ROOT / "src/options/phase27_coverage_report.py").read_text()
    # SYNTHETIC_ONLY may be DEFINED (as an enum member, for completeness of the vocabulary)
    # but must never be ASSIGNED anywhere in the real matrix-building logic.
    assert "CoverageCell.SYNTHETIC_ONLY" not in src.replace('SYNTHETIC_ONLY = "synthetic_only"', "")


def test_merge_layer_never_silently_picks_a_value_on_conflict():
    """Part 7: 'DO NOT choose the better-looking value. Record the
    conflict.' -- a structural guard against ever adding logic that
    silently resolves a MergeConflict."""
    src = (REPO_ROOT / "src/options/phase27_merge.py").read_text()
    forbidden = ("prefer_higher_value", "prefer_better_looking", "silently_resolve", "choose_best_value")
    for pattern in forbidden:
        assert pattern not in src


def test_corporate_action_module_never_asserts_a_confirmed_merge():
    src = (REPO_ROOT / "src/options/phase27_corporate_actions.py").read_text()
    forbidden = ("CONFIRMED_MERGE", "auto_merge_legacy_contract", "silently_repair")
    for pattern in forbidden:
        assert pattern not in src
