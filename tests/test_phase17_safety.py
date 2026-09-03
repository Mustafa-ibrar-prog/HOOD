"""Phase 17 Final Safety Check: multi-issuer SEC data certification
remains DATA CERTIFICATION ONLY -- no alpha hypothesis, no trading
strategy, no order, no prior-phase modification, no fabricated/
interpolated SEC data, no future-data/holdout access.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE17_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase17_*.py"))
PHASE17_SRC_MODULES = [
    "src/data/sec_period_semantics.py",
    "src/data/sec_certification.py",
]
FORBIDDEN_IMPORT_PREFIXES = ("src.execution", "src.orchestrator")
FORBIDDEN_CALLS = ("place_equity_order", "place_option_order", "place_crypto_order", "submit_order", "cancel_equity_order", "cancel_option_order")


def _all_phase17_files():
    return [REPO_ROOT / rel for rel in PHASE17_SRC_MODULES] + list(PHASE17_SCRIPTS)


def test_no_phase17_file_imports_the_live_execution_or_orchestrator_path():
    for path in _all_phase17_files():
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


def test_no_phase17_file_references_a_live_order_placement_call():
    for path in _all_phase17_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_no_phase17_file_functionally_touches_a_prior_phase_hypothesis():
    prior_ids = (
        ("MR-002", "P7-VOLANOM-A", "P7-VOLANOM-A-DEV1", "P9-VOLCLUST-A")
        + tuple(f"P10-VP-{i:03d}" for i in range(1, 11))
        + tuple(f"P11-VCE-{i:03d}" for i in range(1, 7))
        + tuple(f"P12-CSRS-{i:03d}" for i in range(1, 11))
        + tuple(f"P13-OID-{i:03d}" for i in range(1, 9))
    )
    forbidden_patterns = tuple(f'"{hid}"' for hid in prior_ids) + tuple(f"'{hid}'" for hid in prior_ids)
    for path in _all_phase17_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} references a prior-phase hypothesis id via {pattern!r}"


def test_phase17_has_no_hypothesis_family_or_discovery_script():
    names = {p.name for p in PHASE17_SCRIPTS}
    assert not any("preregister" in n for n in names)
    assert not any("discovery_campaign" in n for n in names)
    assert not any("hypothesis" in n for n in names)


def test_no_phase17_file_computes_alpha_statistics():
    forbidden_patterns = (
        "compute_ic_series", "compute_pearson_ic_series", "cross_sectional_quantile_returns",
        "deflated_sharpe_ratio", "probability_of_backtest_overfitting", "BacktestEngine(",
        "run_research_backtest(", "sharpe_ratio(", "sortino", "win_rate", "future_return",
        "expectancy", "strategy_pnl", "future_absolute_return", "future_realized_volatility",
        "PearsonIC", "SpearmanIC", "correlation_with_return",
    )
    for path in _all_phase17_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to compute an alpha/return statistic via {pattern!r}"


def test_no_phase17_file_fabricates_or_interpolates_sec_data():
    forbidden_patterns = ("interpolate(", "np.interp", "fabricated_value", "synthetic_fact", "estimated_publication_time", "4:00 PM", "16:00:00")
    for path in _all_phase17_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate/interpolate SEC data via {pattern!r}"


def test_no_phase17_file_touches_development_validation_or_final_holdout_data():
    for path in PHASE17_SCRIPTS:
        source = path.read_text()
        assert "PartitionLifecycleStage.VALIDATION" not in source
        assert "PartitionLifecycleStage.FINAL_HOLDOUT" not in source
        assert "PartitionLifecycleStage.DEVELOPMENT" not in source


def test_no_phase17_file_writes_to_the_discovery_development_gate():
    for path in _all_phase17_files():
        if not path.is_file():
            continue
        source = path.read_text()
        assert "gate_store.transition(" not in source
        assert "DiscoveryDevelopmentGateStore(" not in source


def test_no_phase17_file_purchases_or_subscribes():
    forbidden_patterns = ("subscribe(", "create_account(", "purchase(", "api_key=", "API_KEY=")
    for path in _all_phase17_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} references {pattern!r} -- no paid subscription/account may be created this phase"


def test_universe_survivorship_status_is_not_upgraded():
    forbidden_patterns = ("POINT_IN_TIME_AVAILABLE", "survivorship_bias_status=\"", "SURVIVORSHIP_FREE")
    for path in _all_phase17_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to upgrade the universe's survivorship status via {pattern!r}"


def test_phase17_certification_report_never_ranks_or_scores_predictive_value():
    """Part 15's cross-issuer comparison is about DATA reliability, not
    predictive value -- explicit static guard against the two concepts
    blurring in the certification report script."""
    for path in PHASE17_SCRIPTS:
        source = path.read_text()
        for pattern in ("predictive_score", "signal_strength", "rank_by_ic", "alpha_score"):
            assert pattern not in source, f"{path} appears to score predictive value via {pattern!r}"
