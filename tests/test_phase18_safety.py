"""Phase 18 Final Safety Check: options data/instrument architecture
only -- no options alpha hypothesis, no trading strategy, no order
placement, no fabricated/interpolated historical options data, no
prior-phase modification, no validation/holdout access.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE18_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase18_*.py"))
PHASE18_SRC_MODULES = [
    "src/options/instrument.py",
    "src/options/chain.py",
    "src/options/greeks.py",
    "src/options/implied_volatility.py",
    "src/options/liquidity.py",
    "src/options/point_in_time.py",
    "src/options/quality.py",
    "src/options/store.py",
    "src/options/position.py",
    "src/options/capability_audit.py",
    "src/execution/asset_class_restriction.py",
]
FORBIDDEN_IMPORT_PREFIXES = ("src.execution.gateway", "src.execution.live_client", "src.orchestrator")
FORBIDDEN_CALLS = ("place_equity_order", "place_option_order", "place_crypto_order", "submit_order", "cancel_equity_order", "cancel_option_order", "review_option_order")


def _all_phase18_files():
    return [REPO_ROOT / rel for rel in PHASE18_SRC_MODULES] + list(PHASE18_SCRIPTS)


def test_no_phase18_file_imports_the_live_order_placement_path():
    for path in _all_phase18_files():
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


def test_no_phase18_file_references_a_live_order_placement_call():
    """src/execution/asset_class_restriction.py and its demo script are
    exempt: they legitimately NAME place_equity_order/review_equity_order/
    cancel_equity_order to document their real, confirmed absence
    elsewhere in the codebase -- neither calls any of them (see
    test_place_equity_order_never_called_anywhere_in_src in
    test_execution_asset_class_restriction.py for the call-form check)."""
    exempt = {
        REPO_ROOT / "src" / "execution" / "asset_class_restriction.py",
        REPO_ROOT / "scripts" / "phase18_step0_options_capability_audit.py",
    }
    for path in _all_phase18_files():
        if not path.is_file() or path in exempt:
            continue
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_no_phase18_file_functionally_touches_a_prior_phase_hypothesis():
    prior_ids = (
        ("MR-002", "P7-VOLANOM-A", "P7-VOLANOM-A-DEV1", "P9-VOLCLUST-A")
        + tuple(f"P10-VP-{i:03d}" for i in range(1, 11))
        + tuple(f"P11-VCE-{i:03d}" for i in range(1, 7))
        + tuple(f"P12-CSRS-{i:03d}" for i in range(1, 11))
        + tuple(f"P13-OID-{i:03d}" for i in range(1, 9))
    )
    forbidden_patterns = tuple(f'"{hid}"' for hid in prior_ids) + tuple(f"'{hid}'" for hid in prior_ids)
    for path in _all_phase18_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} references a prior-phase hypothesis id via {pattern!r}"


def test_phase18_has_no_hypothesis_family_or_discovery_script():
    """Part 19: no options alpha hypothesis, no research family this
    phase -- it is data/instrument architecture only."""
    names = {p.name for p in PHASE18_SCRIPTS}
    assert not any("preregister" in n for n in names)
    assert not any("discovery_campaign" in n for n in names)
    assert not any("hypothesis" in n for n in names)


def test_no_phase18_file_computes_alpha_statistics():
    forbidden_patterns = (
        "compute_ic_series", "compute_pearson_ic_series", "cross_sectional_quantile_returns",
        "deflated_sharpe_ratio", "probability_of_backtest_overfitting", "BacktestEngine(",
        "run_research_backtest(", "sharpe_ratio(", "sortino", "win_rate", "future_return",
        "expectancy", "strategy_pnl", "PearsonIC", "SpearmanIC", "correlation_with_return",
    )
    for path in _all_phase18_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to compute an alpha/return statistic via {pattern!r}"


def test_no_phase18_file_fabricates_or_interpolates_historical_options_data():
    """Part 18 (absolute): no interpolation/synthesis/reconstruction of
    unavailable historical option data, no assumed IV/bid-ask/volume/OI,
    no manufactured Greeks or contract availability."""
    forbidden_patterns = (
        "interpolate(", "np.interp", "synthetic_quote", "fabricated_quote", "assumed_iv", "assumed_bid",
        "assumed_ask", "manufactured_greeks", "reconstruct_historical",
    )
    for path in _all_phase18_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate/interpolate historical options data via {pattern!r}"


def test_historical_chain_methods_raise_rather_than_pretend_to_work():
    """Static guarantee backing Part 4/18: get_historical_chain and
    get_as_of_chain must each contain the word 'raise' in their body --
    they must not silently return a value."""
    source = (REPO_ROOT / "src" / "options" / "store.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ("get_historical_chain", "get_as_of_chain"):
            body_source = ast.get_source_segment(source, node) or ""
            assert "raise" in body_source, f"{node.name} does not raise -- it must not pretend historical data is available"


def test_no_phase18_file_touches_development_validation_or_final_holdout_data():
    for path in PHASE18_SCRIPTS:
        source = path.read_text()
        assert "PartitionLifecycleStage.VALIDATION" not in source
        assert "PartitionLifecycleStage.FINAL_HOLDOUT" not in source
        assert "PartitionLifecycleStage.DEVELOPMENT" not in source


def test_no_phase18_file_writes_to_the_discovery_development_gate():
    for path in _all_phase18_files():
        if not path.is_file():
            continue
        source = path.read_text()
        assert "gate_store.transition(" not in source
        assert "DiscoveryDevelopmentGateStore(" not in source


def test_no_phase18_file_purchases_or_subscribes():
    forbidden_patterns = ("subscribe(", "create_account(", "purchase(", "api_key=", "API_KEY=")
    for path in _all_phase18_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} references {pattern!r} -- no paid subscription/account may be created this phase"


def test_no_live_or_paper_trading_enabled_by_this_phase():
    """No Phase 18 file flips live_trading_confirmed, live_auto_execute,
    or otherwise touches Settings' trading-mode switches."""
    forbidden_patterns = ("live_trading_confirmed=True", "live_auto_execute=True", "trading_mode=\"live\"", "trading_mode='live'")
    for path in _all_phase18_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to enable live/paper trading via {pattern!r}"
