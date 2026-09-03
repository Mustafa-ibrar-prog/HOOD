"""Phase 25 Final Safety Check (Part 24): historical options data
PROVIDER VALIDATION only -- no new alpha hypothesis, no feature
research, no strategy development, no P&L optimization, no backtest,
no paper/live order, no VALIDATION/FINAL_HOLDOUT access, no vendor
purchased, no payment credential stored, no account created with a
paid vendor, no vendor-specific concrete implementation (provider-
agnostic design only), no fabricated field, and Part 26's decision
vocabulary / Part 4's matrix vocabulary are exactly the required fixed
sets.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE25_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase25_*.py"))
PHASE25_SRC_MODULES = [
    "src/options/provider_field_validation.py",
    "src/options/provider_readiness_scorecard.py",
    "src/options/provider_ingestion_pipeline.py",
    "src/options/data_quality_certification.py",
    "src/options/provider_validation_decision.py",
]
FORBIDDEN_IMPORT_PREFIXES = ("src.execution.gateway", "src.execution.live_client", "src.orchestrator")
FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order", "submit_order",
    "cancel_equity_order", "cancel_option_order", "review_option_order", "review_equity_order",
)


def _all_phase25_files():
    return [REPO_ROOT / rel for rel in PHASE25_SRC_MODULES] + list(PHASE25_SCRIPTS)


def test_phase25_files_exist():
    for rel in PHASE25_SRC_MODULES:
        assert (REPO_ROOT / rel).is_file(), f"missing {rel}"
    assert len(PHASE25_SCRIPTS) >= 1


def test_no_phase25_file_imports_the_live_order_placement_path():
    for path in _all_phase25_files():
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


def test_no_phase25_file_references_a_live_or_paper_order_placement_call():
    for path in _all_phase25_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_no_phase25_file_creates_a_strategy_backtest_or_hypothesis():
    """Part 24: 'No new alpha hypotheses. No feature research. No
    strategy development. No P&L optimization. No backtests.'"""
    forbidden_patterns = (
        "LiveStrategy(", "PaperStrategy(", "StrategyExecutor(", "connect_alpha_to_execution",
        "Hypothesis(", "HypothesisRegistry(", "PreregistrationRecord(", "compute_ic_series(",
        "grid_search(", "optimize_parameters(", "run_backtest(",
    )
    for path in _all_phase25_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to register a hypothesis/backtest/strategy via {pattern!r}"


def test_no_phase25_file_implements_a_vendor_specific_store():
    """Part 16/22 carried forward: provider-agnostic design only."""
    forbidden_class_name_fragments = (
        "class PolygonStore", "class ThetaDataStore", "class DatabentoStore", "class OratsStore",
        "class CboeStore", "class OptionMetricsStore", "class TradierStore", "class RobinhoodOptionStore",
    )
    for path in _all_phase25_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_class_name_fragments:
            assert pattern not in source, f"{path} appears to implement a vendor-specific store via {pattern!r}"


def test_no_phase25_file_touches_development_validation_or_final_holdout_data():
    for path in PHASE25_SCRIPTS:
        source = path.read_text()
        assert "PartitionLifecycleStage.VALIDATION" not in source
        assert "PartitionLifecycleStage.FINAL_HOLDOUT" not in source
        assert "PartitionLifecycleStage.DEVELOPMENT" not in source


def test_no_phase25_file_fabricates_a_historical_field():
    forbidden_patterns = (
        "fabricated_bid", "fabricated_ask", "fabricated_oi", "fabricated_iv", "fabricated_greeks",
        "assumed_historical_bid", "assumed_historical_ask", "synthetic_historical_quote",
        "reconstructed_and_presented_as_observed",
    )
    for path in _all_phase25_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate a historical field via {pattern!r}"


def test_no_phase25_file_purchases_a_vendor_or_stores_a_real_api_key():
    forbidden_patterns = (
        "purchase(", "create_account(", "api_key=\"", "API_KEY=\"", "stripe.", "checkout.",
        "credit_card", "payment_method=", "ORATS_API_KEY=\"", "orats_api_key=\"",
    )
    for path in _all_phase25_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to purchase/store credentials for a vendor via {pattern!r}"


def test_no_live_or_paper_trading_enabled_by_this_phase():
    forbidden_patterns = ("live_trading_confirmed=True", "live_auto_execute=True", "trading_mode=\"live\"", "trading_mode='live'")
    for path in _all_phase25_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to enable live/paper trading via {pattern!r}"


def test_field_validation_matrix_uses_only_part4s_exact_four_values():
    from src.options.provider_field_validation import FieldClassification
    assert {v.value for v in FieldClassification} == {
        "verified_available", "verified_unavailable", "claimed_available_unverified", "unknown",
    }


def test_final_decision_uses_only_part26s_exact_five_values():
    from src.options.provider_validation_decision import FinalDecision
    assert {v.value for v in FinalDecision} == {
        "orats_verified_research_ready", "orats_promising_but_unverified",
        "alternative_provider_verified", "no_provider_verified",
        "historical_options_data_still_insufficient",
    }


def test_final_decision_constant_is_not_orats_verified_research_ready():
    """No live probe was ever made this phase -- the strongest honest
    decision is PROMISING_BUT_UNVERIFIED, never the VERIFIED variant."""
    from src.options.provider_validation_decision import FINAL_DECISION, FinalDecision
    assert FINAL_DECISION != FinalDecision.ORATS_VERIFIED_RESEARCH_READY


def test_certification_spec_defines_no_scored_results():
    from src.options.data_quality_certification import CertificationStatus
    assert list(CertificationStatus) == [CertificationStatus.NOT_YET_ASSESSED]


def test_ingestion_pipeline_module_implements_no_concrete_provider():
    """Every class in the ingestion-pipeline module is a Protocol,
    dataclass, or Enum -- never a concrete provider-bound class."""
    interfaces_path = REPO_ROOT / "src/options/provider_ingestion_pipeline.py"
    tree = ast.parse(interfaces_path.read_text(), filename=str(interfaces_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = [b.id if isinstance(b, ast.Name) else getattr(b, "attr", "") for b in node.bases]

            def _decorator_name(d):
                target = d.func if isinstance(d, ast.Call) else d
                return target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")

            decorators = [_decorator_name(d) for d in node.decorator_list]
            is_protocol = "Protocol" in bases
            is_dataclass = "dataclass" in decorators
            is_enum = "Enum" in bases
            assert is_protocol or is_dataclass or is_enum, f"{node.name} looks like a concrete implementation"
