"""Phase 24 Final Safety Check (Part 20/22): infrastructure/data-source
audit only -- no new alpha hypothesis, no backtest, no strategy, no
parameter optimization, no paper/live order, no VALIDATION/FINAL_HOLDOUT
access, no vendor purchased, no large dataset downloaded, no
vendor-specific implementation (provider-agnostic interfaces only), no
fabricated historical field, no live data entering a historical
dataset.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE24_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase24_*.py"))
PHASE24_SRC_MODULES = [
    "src/options/historical_data_interfaces.py",
    "src/options/historical_depth_audit.py",
    "src/options/vendor_scorecard.py",
]
FORBIDDEN_IMPORT_PREFIXES = ("src.execution.gateway", "src.execution.live_client", "src.orchestrator")
FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order", "submit_order",
    "cancel_equity_order", "cancel_option_order", "review_option_order", "review_equity_order",
)


def _all_phase24_files():
    return [REPO_ROOT / rel for rel in PHASE24_SRC_MODULES] + list(PHASE24_SCRIPTS)


def test_phase24_files_exist():
    for rel in PHASE24_SRC_MODULES:
        assert (REPO_ROOT / rel).is_file(), f"missing {rel}"
    assert len(PHASE24_SCRIPTS) >= 1


def test_no_phase24_file_imports_the_live_order_placement_path():
    for path in _all_phase24_files():
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


def test_no_phase24_file_references_a_live_or_paper_order_placement_call():
    for path in _all_phase24_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_no_phase24_file_creates_a_strategy_backtest_or_hypothesis():
    """Part 20: 'No new alpha hypotheses. No backtest. No strategy. No
    parameter optimization. No P&L optimization.'"""
    forbidden_patterns = (
        "LiveStrategy(", "PaperStrategy(", "StrategyExecutor(", "connect_alpha_to_execution",
        "Hypothesis(", "HypothesisRegistry(", "PreregistrationRecord(", "compute_ic_series(",
        "grid_search(", "optimize_parameters(",
    )
    for path in _all_phase24_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to register a hypothesis/backtest/strategy via {pattern!r}"


def test_no_phase24_file_implements_a_vendor_specific_store():
    """Part 16: 'Do NOT implement a vendor-specific system yet. Use
    provider-agnostic interfaces.' A heuristic guard: no vendor name
    appears as a class name prefix/suffix for any Store class."""
    forbidden_class_name_fragments = (
        "class PolygonStore", "class ThetaDataStore", "class DatabentoStore", "class OratsStore",
        "class CboeStore", "class OptionMetricsStore", "class TradierStore", "class RobinhoodOptionStore",
    )
    for path in _all_phase24_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_class_name_fragments:
            assert pattern not in source, f"{path} appears to implement a vendor-specific store via {pattern!r}"


def test_interfaces_module_defines_only_protocols_and_dataclasses_no_concrete_implementation():
    interfaces_path = REPO_ROOT / "src/options/historical_data_interfaces.py"
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
            assert is_protocol or is_dataclass or is_enum, f"{node.name} in historical_data_interfaces.py is neither a Protocol, dataclass, nor Enum -- looks like a concrete implementation"


def test_no_phase24_file_touches_development_validation_or_final_holdout_data():
    for path in PHASE24_SCRIPTS:
        source = path.read_text()
        assert "PartitionLifecycleStage.VALIDATION" not in source
        assert "PartitionLifecycleStage.FINAL_HOLDOUT" not in source
        assert "PartitionLifecycleStage.DEVELOPMENT" not in source


def test_no_phase24_file_fabricates_historical_bid_ask_oi_iv_greeks():
    forbidden_patterns = (
        "fabricated_bid", "fabricated_ask", "fabricated_oi", "fabricated_iv", "fabricated_greeks",
        "assumed_historical_bid", "assumed_historical_ask", "synthetic_historical_quote", "reconstructed_and_presented_as_observed",
    )
    for path in _all_phase24_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate a historical field via {pattern!r}"


def test_no_phase24_file_treats_live_quote_data_as_historical():
    """Part 2: 'Do not infer historical availability from live
    functionality.' A textual guard: no file claims a live-fetched value
    stands in for a historical observation."""
    forbidden_patterns = ("live_quote_as_historical", "current_quote_used_as_past", "backfilled_from_live")
    for path in _all_phase24_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to treat live data as historical via {pattern!r}"


def test_no_phase24_file_purchases_a_vendor_or_stores_a_real_api_key():
    forbidden_patterns = ("purchase(", "create_account(", "api_key=\"", "API_KEY=\"", "stripe.", "checkout.")
    for path in _all_phase24_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to purchase/store credentials for a vendor via {pattern!r}"


def test_no_phase24_file_downloads_a_large_dataset():
    """Part 19: 'Do NOT download millions of records... do not build a
    new historical dataset yet.' A heuristic guard against a bulk-fetch
    loop pattern."""
    forbidden_patterns = ("for page in range(1000", "while True:  # bulk download", "download_full_history(", "bulk_fetch_all_contracts(")
    for path in _all_phase24_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to bulk-download a large dataset via {pattern!r}"


def test_no_live_or_paper_trading_enabled_by_this_phase():
    forbidden_patterns = ("live_trading_confirmed=True", "live_auto_execute=True", "trading_mode=\"live\"", "trading_mode='live'")
    for path in _all_phase24_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to enable live/paper trading via {pattern!r}"


def test_no_phase24_file_declares_data_capability_validated():
    """Part 23's vocabulary is HISTORICAL_OPTIONS_DATA_READY(_WITH_LIMITATIONS)/
    PARTIALLY_AVAILABLE/INSUFFICIENT/UNAVAILABLE -- never 'VALIDATED.'"""
    forbidden_patterns = ('= "VALIDATED"', '== "VALIDATED"')
    for path in _all_phase24_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to declare something VALIDATED via {pattern!r}"
