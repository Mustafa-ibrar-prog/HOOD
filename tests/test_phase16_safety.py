"""Phase 16 Final Safety Check: SEC data integration remains a
DATA/RESEARCH-FOUNDATION phase only -- no alpha hypothesis, no trading
strategy, no order, no prior-phase modification, no fabricated/
interpolated SEC data. Mirrors the established safety-test pattern.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE16_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase16_*.py"))
PHASE16_SRC_MODULES = [
    "src/data/sec_filing_store.py",
    "src/data/sec_timestamp_policy.py",
    "src/data/sec_fact_quality.py",
    "src/data/sec_concepts.py",
    "src/data/sec_snapshot.py",
    "src/data/sec_dataset.py",
]
FORBIDDEN_IMPORT_PREFIXES = ("src.execution", "src.orchestrator")
FORBIDDEN_CALLS = ("place_equity_order", "place_option_order", "place_crypto_order", "submit_order", "cancel_equity_order", "cancel_option_order")


def _all_phase16_files():
    return [REPO_ROOT / rel for rel in PHASE16_SRC_MODULES] + list(PHASE16_SCRIPTS)


def test_no_phase16_file_imports_the_live_execution_or_orchestrator_path():
    for path in _all_phase16_files():
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


def test_no_phase16_file_references_a_live_order_placement_call():
    for path in _all_phase16_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_no_phase16_file_functionally_touches_a_prior_phase_hypothesis():
    prior_ids = (
        ("MR-002", "P7-VOLANOM-A", "P7-VOLANOM-A-DEV1", "P9-VOLCLUST-A")
        + tuple(f"P10-VP-{i:03d}" for i in range(1, 11))
        + tuple(f"P11-VCE-{i:03d}" for i in range(1, 7))
        + tuple(f"P12-CSRS-{i:03d}" for i in range(1, 11))
        + tuple(f"P13-OID-{i:03d}" for i in range(1, 9))
    )
    forbidden_patterns = tuple(f'"{hid}"' for hid in prior_ids) + tuple(f"'{hid}'" for hid in prior_ids)
    for path in _all_phase16_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} references a prior-phase hypothesis id via {pattern!r}"


def test_phase16_has_no_hypothesis_family_or_discovery_script():
    """Part 16: no alpha hypothesis registry entry, no research family
    this phase -- it is a data-foundation phase only."""
    names = {p.name for p in PHASE16_SCRIPTS}
    assert not any("preregister" in n for n in names)
    assert not any("discovery_campaign" in n for n in names)
    assert not any("hypothesis" in n for n in names)


def test_no_phase16_file_computes_alpha_statistics():
    """Part 16: 'This requirement is absolute' -- no IC/Sharpe/Sortino/
    PBO/DSR/expectancy/win-rate/backtest/future-return/predictive-power
    computation anywhere in this phase's new code."""
    forbidden_patterns = (
        "compute_ic_series", "compute_pearson_ic_series", "cross_sectional_quantile_returns",
        "deflated_sharpe_ratio", "probability_of_backtest_overfitting", "BacktestEngine(",
        "run_research_backtest(", "sharpe_ratio(", "sortino", "win_rate", "future_return",
        "expectancy", "strategy_pnl", "future_absolute_return", "future_realized_volatility",
    )
    for path in _all_phase16_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to compute an alpha/return statistic via {pattern!r}"


def test_no_phase16_file_fabricates_or_interpolates_sec_data():
    """Part 22: 'Do NOT fabricate or interpolate SEC data.' A fact's
    value/timestamp must come from a real, cited probe -- no code path
    invents a value, interpolates between two real observations, or
    manufactures a fake accepted-timestamp (e.g. a hardcoded 16:00
    publication time)."""
    forbidden_patterns = ("interpolate(", "np.interp", "fabricated_value", "synthetic_fact", "estimated_publication_time", "4:00 PM", "16:00:00")
    for path in _all_phase16_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate/interpolate SEC data via {pattern!r}"


def test_no_phase16_file_touches_development_validation_or_final_holdout_data():
    for path in PHASE16_SCRIPTS:
        source = path.read_text()
        assert "PartitionLifecycleStage.VALIDATION" not in source
        assert "PartitionLifecycleStage.FINAL_HOLDOUT" not in source
        assert "PartitionLifecycleStage.DEVELOPMENT" not in source


def test_no_phase16_file_writes_to_the_discovery_development_gate():
    for path in _all_phase16_files():
        if not path.is_file():
            continue
        source = path.read_text()
        assert "gate_store.transition(" not in source
        assert "DiscoveryDevelopmentGateStore(" not in source


def test_no_phase16_file_purchases_or_subscribes():
    forbidden_patterns = ("subscribe(", "create_account(", "purchase(", "api_key=", "API_KEY=")
    for path in _all_phase16_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} references {pattern!r} -- no paid subscription/account may be created this phase"


def test_universe_survivorship_status_is_not_upgraded():
    """Part 12: the existing universe must remain
    CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED -- no Phase 16 file claims a
    point-in-time-constituent or survivorship-free universe."""
    forbidden_patterns = ("POINT_IN_TIME_AVAILABLE", "survivorship_bias_status=\"", "SURVIVORSHIP_FREE")
    for path in _all_phase16_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to upgrade the universe's survivorship status via {pattern!r}"
