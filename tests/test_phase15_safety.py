"""Phase 15 Final Safety Check: this phase is a DATA ARCHITECTURE AUDIT
only — no P15 hypothesis family, no alpha test, no order, no paid
subscription. Mirrors the established safety-test pattern, scoped to
what an architecture-only phase actually touches.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE15_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase15_*.py"))
PHASE15_SRC_MODULES = [
    "src/data/timestamp_model.py",
    "src/data/source_profile.py",
    "src/data/generic_quality.py",
    "src/data/store_interfaces.py",
]
FORBIDDEN_IMPORT_PREFIXES = ("src.execution", "src.orchestrator")
FORBIDDEN_CALLS = ("place_equity_order", "place_option_order", "place_crypto_order", "submit_order", "cancel_equity_order", "cancel_option_order")


def _all_phase15_files():
    return [REPO_ROOT / rel for rel in PHASE15_SRC_MODULES] + list(PHASE15_SCRIPTS)


def test_no_phase15_file_imports_the_live_execution_or_orchestrator_path():
    for path in _all_phase15_files():
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


def test_no_phase15_file_references_a_live_order_placement_call():
    for path in _all_phase15_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_no_phase15_file_functionally_touches_a_prior_phase_hypothesis():
    prior_ids = (
        ("MR-002", "P7-VOLANOM-A", "P7-VOLANOM-A-DEV1", "P9-VOLCLUST-A")
        + tuple(f"P10-VP-{i:03d}" for i in range(1, 11))
        + tuple(f"P11-VCE-{i:03d}" for i in range(1, 7))
        + tuple(f"P12-CSRS-{i:03d}" for i in range(1, 11))
        + tuple(f"P13-OID-{i:03d}" for i in range(1, 9))
    )
    forbidden_patterns = tuple(f'"{hid}"' for hid in prior_ids) + tuple(f"'{hid}'" for hid in prior_ids)
    for path in _all_phase15_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} references a prior-phase hypothesis id via {pattern!r}"


def test_phase15_has_no_hypothesis_family_or_discovery_script():
    """Part 1/18/25: no alpha hypothesis, no discovery campaign this
    phase — it is architecture/audit only."""
    names = {p.name for p in PHASE15_SCRIPTS}
    assert not any("preregister" in n for n in names)
    assert not any("discovery_campaign" in n for n in names)


def test_no_phase15_file_computes_alpha_statistics():
    """Part 18: no IC/Sharpe/PBO/DSR/strategy-return computation anywhere
    in this phase's new code — this is an architecture phase, not
    discovery."""
    forbidden_patterns = (
        "compute_ic_series", "compute_pearson_ic_series", "cross_sectional_quantile_returns",
        "deflated_sharpe_ratio", "probability_of_backtest_overfitting", "BacktestEngine(",
        "run_research_backtest(", "sharpe_ratio(",
    )
    for path in _all_phase15_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to compute an alpha statistic via {pattern!r}"


def test_no_phase15_file_fabricates_historical_microstructure_or_intraday_data():
    """Part 4's hard-stop discipline carries forward: no code path
    synthesizes historical bid/ask, order flow, or intraday bars — the
    audit found intraday history unavailable and must not paper over
    that by manufacturing it."""
    forbidden_patterns = (
        "estimated_spread", "synthetic_spread", "fake_bid", "fake_ask",
        "bid = close", "ask = close", "synthetic_intraday", "fabricated",
    )
    for path in _all_phase15_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate historical data via {pattern!r}"


def test_no_phase15_file_references_a_paid_subscription_or_purchase():
    """Part 11: this phase must not purchase a data subscription, create
    a paid account, or commit funds."""
    forbidden_patterns = ("subscribe(", "create_account(", "purchase(", "api_key=", "API_KEY=")
    for path in _all_phase15_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} references {pattern!r} — no paid subscription/account may be created this phase"


def test_no_phase15_script_touches_development_validation_or_final_holdout_data():
    for path in PHASE15_SCRIPTS:
        source = path.read_text()
        assert "PartitionLifecycleStage.VALIDATION" not in source
        assert "PartitionLifecycleStage.FINAL_HOLDOUT" not in source
        assert "PartitionLifecycleStage.DEVELOPMENT" not in source


def test_no_phase15_script_writes_to_the_discovery_development_gate():
    """No hypothesis was registered this phase — no gate transition of
    any kind should appear."""
    for path in PHASE15_SCRIPTS:
        source = path.read_text()
        assert "gate_store.transition(" not in source
        assert "DiscoveryDevelopmentGateStore(" not in source
