"""Phase 26 Final Safety Check (Part 14): historical options DATA
CERTIFICATION only -- no alpha hypothesis, no signal search, no
parameter optimization, no strategy rule, no contract-selected-because-
it-performed-well, no profitability backtest, no alpha ranking, no
claimed edge, no live/paper order, no VALIDATION/FINAL_HOLDOUT access,
no vendor purchased, no payment credential stored, no fabricated
historical field.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE26_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase26_*.py"))
PHASE26_SRC_MODULES = [
    "src/options/phase26_lean_sample_parser.py",
    "src/options/black_scholes.py",
    "src/options/phase26_dataset_builder.py",
    "src/options/phase26_ingest.py",
    "src/options/phase26_quality_rules.py",
    "src/options/phase26_pit_certification.py",
    "src/options/phase26_execution_realism.py",
    "src/options/phase26_iv_greeks_certification.py",
    "src/options/phase26_chain_reconstruction.py",
    "src/options/phase26_certification_score.py",
    "src/options/phase26_final_gate.py",
    "src/options/phase26_dataset_persistence.py",
    "src/options/phase26_certified_dataset.py",
]
FORBIDDEN_IMPORT_PREFIXES = ("src.execution.gateway", "src.execution.live_client", "src.orchestrator")
FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order", "submit_order",
    "cancel_equity_order", "cancel_option_order", "review_option_order", "review_equity_order",
)


def _all_phase26_files():
    return [REPO_ROOT / rel for rel in PHASE26_SRC_MODULES] + list(PHASE26_SCRIPTS)


def test_phase26_files_exist():
    for rel in PHASE26_SRC_MODULES:
        assert (REPO_ROOT / rel).is_file(), f"missing {rel}"
    assert len(PHASE26_SCRIPTS) >= 1


def test_no_phase26_file_imports_the_live_order_placement_path():
    for path in _all_phase26_files():
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


def test_no_phase26_file_references_a_live_or_paper_order_placement_call():
    for path in _all_phase26_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_no_phase26_file_creates_a_strategy_backtest_or_hypothesis():
    """Part 14: 'Absolutely do NOT: search for profitable signals,
    optimize parameters, create strategy rules, select contracts because
    they performed well, run backtests for profitability, rank alpha
    hypotheses, claim an edge, create live orders.'"""
    forbidden_patterns = (
        "LiveStrategy(", "PaperStrategy(", "StrategyExecutor(", "connect_alpha_to_execution",
        "Hypothesis(", "HypothesisRegistry(", "PreregistrationRecord(", "compute_ic_series(",
        "grid_search(", "optimize_parameters(", "run_backtest(", "profitable_signal", "alpha_rank",
        "claimed_edge", "select_because_performed_well",
    )
    for path in _all_phase26_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to register a hypothesis/backtest/strategy via {pattern!r}"


def test_no_phase26_file_touches_development_validation_or_final_holdout_data():
    for path in PHASE26_SCRIPTS:
        source = path.read_text()
        assert "PartitionLifecycleStage.VALIDATION" not in source
        assert "PartitionLifecycleStage.FINAL_HOLDOUT" not in source
        assert "PartitionLifecycleStage.DEVELOPMENT" not in source


def test_no_phase26_file_purchases_a_vendor_or_stores_a_real_api_key():
    forbidden_patterns = (
        "purchase(", "create_account(", "api_key=\"", "API_KEY=\"", "stripe.", "checkout.",
        "credit_card", "payment_method=",
    )
    for path in _all_phase26_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to purchase/store credentials for a vendor via {pattern!r}"


def test_no_live_or_paper_trading_enabled_by_this_phase():
    forbidden_patterns = ("live_trading_confirmed=True", "live_auto_execute=True", "trading_mode=\"live\"", "trading_mode='live'")
    for path in _all_phase26_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to enable live/paper trading via {pattern!r}"


def test_no_phase26_file_fabricates_a_historical_field():
    forbidden_patterns = (
        "fabricated_bid", "fabricated_ask", "fabricated_oi", "fabricated_iv", "fabricated_greeks",
        "assumed_historical_bid", "assumed_historical_ask", "synthetic_historical_quote",
        "reconstructed_and_presented_as_observed",
    )
    for path in _all_phase26_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate a historical field via {pattern!r}"


def test_reconstructed_iv_and_greeks_never_use_observed_provenance():
    """Part 7: reconstructed values must be classified RECONSTRUCTABLE/
    DERIVED, never presented as a vendor-OBSERVED field."""
    source = (REPO_ROOT / "src/options/phase26_iv_greeks_certification.py").read_text()
    assert "IVProvenance.OBSERVED" not in source
    assert "GreeksProvenance.OBSERVED_FROM_SOURCE" not in source
    assert "IVProvenance.DERIVED" in source
    assert "GreeksProvenance.DERIVED_FROM_MODEL" in source


def test_certification_gate_vocabulary_matches_part_11_exactly():
    from src.options.phase26_final_gate import ResearchReadinessGate
    assert {g.value for g in ResearchReadinessGate} == {
        "historical_options_data_insufficient", "historical_options_data_partial",
        "historical_options_research_ready", "historical_options_backtest_ready",
        "historical_options_production_research_ready",
    }


def test_no_phase26_file_declares_a_field_verified_by_actual_data_without_a_real_check():
    """A heuristic honesty guard: every module that asserts
    'verified_by_actual_data' must also reference a real, concrete
    ingestion/parsing function -- not just a bare string label."""
    src = (REPO_ROOT / "src/options/phase26_dataset_builder.py").read_text()
    assert "verified_by_actual_data_this_phase" in src
    assert "LEAN_SAMPLE_SOURCE" in src  # ties the confidence label to a concrete, real, named source


def test_multiplier_assumption_is_never_silently_presented_as_confirmed():
    src = (REPO_ROOT / "src/options/phase26_dataset_builder.py").read_text()
    assert "MULTIPLIER_SOURCE_CONFIRMED = False" in src


def test_no_phase26_file_declares_data_capability_validated_with_wrong_vocabulary():
    forbidden_patterns = ('= "VALIDATED"', '== "VALIDATED"')
    for path in _all_phase26_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to declare something VALIDATED via {pattern!r}"
