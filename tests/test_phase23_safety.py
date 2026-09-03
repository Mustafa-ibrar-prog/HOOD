"""Phase 23 Final Safety Check (Part 26): the P22-OPT-013 adversarial
investigation and tradeable-transformation research must remain
research-only -- no live/paper order, no execution-layer import, no
VALIDATION/FINAL_HOLDOUT access, no re-registration/modification of the
frozen P22-OPT-013 parent, no fabricated historical IV/Greeks/volume/OI/
bid-ask, no live-only field used as historical, deterministic experiment
fingerprints, no hypothesis declared VALIDATED (Part 27's vocabulary is
ROBUST_DISCOVERY_CANDIDATE / FRAGILE_DISCOVERY / OVERLAP_DEPENDENT /
REGIME_DEPENDENT / EXPIRATION_DEPENDENT / MONEYNESS_DEPENDENT /
OUTLIER_DEPENDENT / UNDERLYING_INHERITED / NON_DIRECTIONAL_ONLY /
TRADEABILITY_FAILED / DATA_INSUFFICIENT / REJECTED, plus the separate
TRADEABLE_SIGNAL_* vocabulary -- explicitly never "validated").
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE23_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase23_*.py"))
FORBIDDEN_IMPORT_PREFIXES = ("src.execution.gateway", "src.execution.live_client", "src.orchestrator")
FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order", "submit_order",
    "cancel_equity_order", "cancel_option_order", "review_option_order", "review_equity_order",
)


def test_phase23_files_exist():
    assert len(PHASE23_SCRIPTS) >= 5, "expected step0-step4 Phase 23 scripts to exist"


def test_no_phase23_file_imports_the_live_order_placement_path():
    for path in PHASE23_SCRIPTS:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in FORBIDDEN_IMPORT_PREFIXES:
                    assert not node.module.startswith(prefix), f"{path} imports {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in FORBIDDEN_IMPORT_PREFIXES:
                        assert not alias.name.startswith(prefix), f"{path} imports {alias.name}"


def test_no_phase23_file_references_a_live_or_paper_order_placement_call():
    for path in PHASE23_SCRIPTS:
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_no_phase23_file_creates_a_strategy_object():
    forbidden_patterns = ("LiveStrategy(", "PaperStrategy(", "StrategyExecutor(", "connect_alpha_to_execution")
    for path in PHASE23_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to create/connect a strategy via {pattern!r}"


def test_no_phase23_file_modifies_the_frozen_p22_opt_013_parent():
    """Part 2's explicit instruction: P22-OPT-013 is read (hyp_registry.
    get) to verify it is frozen, but never re-registered/edited with new
    content this phase. Only NEW P23-* ids may be registered, each with
    parent_hypothesis_id='P22-OPT-013'."""
    for path in PHASE23_SCRIPTS:
        source = path.read_text()
        assert 'hypothesis_id="P22-OPT-013", name=' not in source, f"{path} appears to re-register P22-OPT-013"


def test_phase23_investigations_reference_the_frozen_parent():
    step2 = REPO_ROOT / "scripts" / "phase23_step2_preregister_investigation.py"
    assert step2.is_file()
    source = step2.read_text()
    assert 'parent_hypothesis_id=PARENT_ID' in source
    assert 'PARENT_ID = "P22-OPT-013"' in source


def test_no_phase23_file_declares_a_hypothesis_validated():
    forbidden_patterns = (
        'verdict = "VALIDATED"', 'verdict == "VALIDATED"', 'classification = "VALIDATED"', 'return "VALIDATED"',
        'classification == "VALIDATED"',
    )
    for path in PHASE23_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to declare a hypothesis VALIDATED via {pattern!r}"


def test_robust_discovery_candidate_is_never_equated_with_validated():
    step3 = REPO_ROOT / "scripts" / "phase23_step3_investigation_campaign.py"
    source = step3.read_text()
    assert "ROBUST_DISCOVERY_CANDIDATE" in source
    assert "does NOT mean validated" in source or "does not mean validated" in source.lower()


def test_no_phase23_file_touches_development_validation_or_final_holdout_data():
    for path in PHASE23_SCRIPTS:
        source = path.read_text()
        assert "PartitionLifecycleStage.VALIDATION" not in source
        assert "PartitionLifecycleStage.FINAL_HOLDOUT" not in source
        assert "PartitionLifecycleStage.DEVELOPMENT" not in source


def test_no_phase23_file_uses_a_live_only_field_as_historical():
    forbidden_patterns = (
        "historical_bid", "historical_ask", "historical_open_interest", "historical_iv",
        "current_open_interest_as_historical", "assumed_historical_liquidity_score",
    )
    for path in PHASE23_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate a historical liquidity field via {pattern!r}"


def test_no_phase23_file_fabricates_or_interpolates_historical_options_data():
    forbidden_patterns = (
        "interpolate(", "np.interp", "synthetic_quote", "fabricated_quote", "assumed_iv", "assumed_bid",
        "assumed_ask", "manufactured_greeks", "reconstruct_historical", "fabricated_volume", "fabricated_open_interest",
    )
    for path in PHASE23_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate/interpolate historical options data via {pattern!r}"


def test_step1_reproduces_the_exact_phase22_result_or_stops():
    step1 = REPO_ROOT / "scripts" / "phase23_step1_freeze_parent.py"
    source = step1.read_text()
    assert "REPRODUCTION FAILURE" in source
    assert "raise SystemExit" in source


def test_no_phase23_file_fetches_new_mcp_data():
    """Part 24: 'Do NOT automatically fetch new data.'"""
    for path in PHASE23_SCRIPTS:
        source = path.read_text()
        forbidden_patterns = ("get_option_instruments(", "get_option_historicals(", "get_option_quotes(", "get_option_chains(", "mcp__HOOD__")
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fetch new MCP data via {pattern!r}"


def test_step4_never_enters_at_the_same_bar_close_that_produced_the_signal():
    """Part 8's explicit prohibition: entry must use the NEXT bar, never
    the signal bar's own OHLC (which would be an impossible/lookahead
    fill)."""
    step4 = REPO_ROOT / "scripts" / "phase23_step4_tradeable_transformation.py"
    source = step4.read_text()
    assert "entry_idx = i + 1" in source or "entry_idx = i + 2" in source
    assert "bars[i].close" not in source  # entry never uses the signal bar's own close directly
    assert "bars[i].open" not in source  # nor the signal bar's own open


def test_step4_excludes_tick_floor_pinned_near_zero_entries():
    step4 = REPO_ROOT / "scripts" / "phase23_step4_tradeable_transformation.py"
    source = step4.read_text()
    assert "MIN_ENTRY_PRICE" in source


def test_step4_applies_mandatory_outlier_treatment_to_trade_returns():
    step4 = REPO_ROOT / "scripts" / "phase23_step4_tradeable_transformation.py"
    source = step4.read_text()
    assert "TRADE_OUTLIER_DEPENDENT" in source
    assert "winsorize(" in source


def test_no_phase23_file_purchases_or_subscribes():
    forbidden_patterns = ("subscribe(", "create_account(", "purchase(", "api_key=", "API_KEY=")
    for path in PHASE23_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} references {pattern!r}"


def test_no_live_or_paper_trading_enabled_by_this_phase():
    forbidden_patterns = ("live_trading_confirmed=True", "live_auto_execute=True", "trading_mode=\"live\"", "trading_mode='live'")
    for path in PHASE23_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to enable live/paper trading via {pattern!r}"


def test_no_phase23_file_declares_profitability():
    forbidden_patterns = ("is_profitable = True", "claimed_profitable", "profitability_confirmed")
    for path in PHASE23_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to claim profitability via {pattern!r}"


def test_tradeable_grid_is_small_and_bounded():
    """Part 7: 'a tightly bounded grid... Do NOT perform unconstrained
    optimization.'"""
    step2 = REPO_ROOT / "scripts" / "phase23_step2_preregister_investigation.py"
    source = step2.read_text()
    assert "THRESHOLD_GRID = (1.25, 1.50, 1.75, 2.00, 2.50)" in source
    assert "HOLDING_PERIOD_GRID = (1, 3, 5, 10)" in source


def test_no_phase23_file_promotes_a_candidate_to_validation():
    forbidden_patterns = ("promote_to_validation", "PartitionLifecycleStage.VALIDATION", "mark_validated")
    for path in PHASE23_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to promote a candidate to validation via {pattern!r}"
