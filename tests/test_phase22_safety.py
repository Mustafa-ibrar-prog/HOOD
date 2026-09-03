"""Phase 22 Final Safety Check (Part 27): discovery-only options-specific
alpha search -- no live/paper order, no execution-layer import from
research, no VALIDATION/FINAL_HOLDOUT access, no fabricated historical
IV/Greeks/volume/OI/bid-ask, no live-only field used as historical, no
post-hoc hypothesis silently counted as preregistered, no reconstructed-
and-pretended-observed Greek, no hypothesis modified after its result
was computed, deterministic experiment fingerprints, no hypothesis
declared VALIDATED (Part 24's vocabulary is DISCOVERY_SUPPORTED /
INCONCLUSIVE / FRAGILE / REJECTED / INHERITED_FROM_UNDERLYING /
OUTLIER_DEPENDENT / DATA_INSUFFICIENT -- explicitly not "validated").
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE22_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase22_*.py"))
PHASE22_SRC_MODULES = [
    "src/options/price_volatility_proxy.py",
    "src/options/momentum_features.py",
    "src/options/relative_return.py",
]
FORBIDDEN_IMPORT_PREFIXES = ("src.execution.gateway", "src.execution.live_client", "src.orchestrator")
FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order", "submit_order",
    "cancel_equity_order", "cancel_option_order", "review_option_order", "review_equity_order",
)


def _all_phase22_files():
    return [REPO_ROOT / rel for rel in PHASE22_SRC_MODULES] + list(PHASE22_SCRIPTS)


def test_phase22_files_exist():
    assert len(PHASE22_SCRIPTS) >= 3, "expected at least the step1/step2/step3 Phase 22 scripts to exist"
    for rel in PHASE22_SRC_MODULES:
        assert (REPO_ROOT / rel).is_file(), f"missing {rel}"


def test_no_phase22_file_imports_the_live_order_placement_path():
    for path in _all_phase22_files():
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


def test_no_phase22_file_references_a_live_or_paper_order_placement_call():
    for path in _all_phase22_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_no_phase22_file_creates_a_strategy_object():
    forbidden_patterns = ("LiveStrategy(", "PaperStrategy(", "StrategyExecutor(", "connect_alpha_to_execution")
    for path in _all_phase22_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to create/connect a strategy via {pattern!r}"


def test_no_phase22_hypothesis_has_a_parent_other_than_none():
    """Part 3: every P22-OPT-* hypothesis must have parent_hypothesis_id=None
    -- this is a NEW family, not a continuation/replication of any prior
    phase's hypothesis."""
    step2 = REPO_ROOT / "scripts" / "phase22_step2_preregister_hypotheses.py"
    assert step2.is_file()
    source = step2.read_text()
    assert "parent_hypothesis_id=None" in source
    assert "parent_hypothesis_id=hyp_id" not in source
    assert "parent_hypothesis_id=parent_id" not in source
    # never references a Phase 19/20/21 hypothesis id as a parent
    for prefix in ("P19-OPT", "P20-", "P21-"):
        assert f'parent_hypothesis_id="{prefix}' not in source


def test_no_phase22_file_modifies_a_prior_phase_hypothesis_definition():
    for path in PHASE22_SCRIPTS:
        source = path.read_text()
        for i in range(1, 13):
            hid = f"P19-OPT-{i:03d}"
            assert f'hypothesis_id="{hid}", name=' not in source, f"{path} appears to re-register {hid}"
        for hid in ("P19-OPT-004-EXPANDED", "P19-OPT-005-EXPANDED", "P19-OPT-008-EXPANDED", "P19-OPT-009-EXPANDED", "P19-OPT-012-EXPANDED"):
            assert f'hypothesis_id="{hid}", name=' not in source, f"{path} appears to re-register {hid}"


def test_no_phase22_file_revives_p19_opt_009_raw_log_moneyness_as_a_standalone_hypothesis():
    """Theme E's explicit instruction: do NOT revive P19-OPT-009 (raw
    log-moneyness as the sole feature) -- only a genuinely NEW
    interaction term (log_moneyness combined with another independently
    motivated signal) is permitted."""
    step2 = REPO_ROOT / "scripts" / "phase22_step2_preregister_hypotheses.py"
    source = step2.read_text()
    assert '("log_moneyness",)' not in source, "a standalone log_moneyness-only hypothesis would revive the rejected P19-OPT-009"


def test_no_phase22_file_declares_a_hypothesis_validated():
    forbidden_patterns = (
        'verdict = "VALIDATED"', 'verdict == "VALIDATED"', 'classification = "VALIDATED"', 'return "VALIDATED"',
        'final = "VALIDATED"', 'classification == "VALIDATED"',
    )
    for path in _all_phase22_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to declare a hypothesis VALIDATED via {pattern!r}"


def test_discovery_supported_classification_is_documented_as_not_profitable_or_validated():
    step3 = REPO_ROOT / "scripts" / "phase22_step3_discovery_campaign.py"
    assert step3.is_file()
    source = step3.read_text()
    assert "DISCOVERY_SUPPORTED" in source
    assert "NOT profitable" in source or "not profitable" in source.lower()


def test_no_phase22_file_touches_development_validation_or_final_holdout_data():
    for path in PHASE22_SCRIPTS:
        source = path.read_text()
        assert "PartitionLifecycleStage.VALIDATION" not in source
        assert "PartitionLifecycleStage.FINAL_HOLDOUT" not in source
        assert "PartitionLifecycleStage.DEVELOPMENT" not in source


def test_no_phase22_file_uses_a_live_only_field_as_historical():
    forbidden_patterns = (
        "historical_bid", "historical_ask", "historical_open_interest", "historical_iv",
        "current_open_interest_as_historical", "assumed_historical_liquidity_score",
    )
    for path in _all_phase22_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate a historical liquidity field via {pattern!r}"


def test_no_phase22_file_fabricates_or_interpolates_historical_options_data():
    forbidden_patterns = (
        "interpolate(", "np.interp", "synthetic_quote", "fabricated_quote", "assumed_iv", "assumed_bid",
        "assumed_ask", "manufactured_greeks", "reconstruct_historical", "fabricated_volume", "fabricated_open_interest",
    )
    for path in _all_phase22_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate/interpolate historical options data via {pattern!r}"


def test_no_phase22_file_reconstructs_and_pretends_to_observe_greeks():
    step3 = REPO_ROOT / "scripts" / "phase22_step3_discovery_campaign.py"
    source = step3.read_text()
    assert "HISTORICAL_GREEKS_UNAVAILABLE" in source
    forbidden_patterns = ("reconstructed_delta", "assumed_delta", "fabricated_greeks", "synthetic_delta")
    for pattern in forbidden_patterns:
        assert pattern not in source, f"{step3} appears to reconstruct Greeks via {pattern!r}"


def test_relative_return_module_documents_that_rolling_beta_is_not_a_greek():
    source = (REPO_ROOT / "src/options/relative_return.py").read_text()
    assert "NOT delta" in source or "not delta" in source.lower()
    assert "historical Greek" in source or "historical greek" in source.lower()


def test_no_phase22_file_purchases_or_subscribes():
    forbidden_patterns = ("subscribe(", "create_account(", "purchase(", "api_key=", "API_KEY=")
    for path in _all_phase22_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} references {pattern!r}"


def test_no_live_or_paper_trading_enabled_by_this_phase():
    forbidden_patterns = ("live_trading_confirmed=True", "live_auto_execute=True", "trading_mode=\"live\"", "trading_mode='live'")
    for path in _all_phase22_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to enable live/paper trading via {pattern!r}"


def test_cost_model_never_claims_execution_realistic_research_was_produced():
    forbidden = "= ResearchRealismLabel.EXECUTION_REALISTIC_RESEARCH"
    for path in _all_phase22_files():
        if not path.is_file():
            continue
        assert forbidden not in path.read_text(), f"{path} appears to assign the EXECUTION_REALISTIC_RESEARCH label to a real result"


def test_step2_computes_a_deterministic_experiment_fingerprint_per_hypothesis():
    step2 = REPO_ROOT / "scripts" / "phase22_step2_preregister_hypotheses.py"
    source = step2.read_text()
    assert "compute_experiment_fingerprint" in source
    assert "ExperimentDimensions" in source


def test_step1_fetches_no_new_mcp_data():
    """Part 21/23: Phase 22 builds features from the already-gathered
    Phase 19/20 panel -- it must not call any live MCP data-gathering
    tool."""
    step1 = REPO_ROOT / "scripts" / "phase22_step1_build_feature_panel.py"
    source = step1.read_text()
    forbidden_patterns = ("get_option_instruments(", "get_option_historicals(", "get_option_quotes(", "get_option_chains(", "mcp__HOOD__")
    for pattern in forbidden_patterns:
        assert pattern not in source, f"{step1} appears to fetch new MCP data via {pattern!r}"


def test_step3_never_assumes_unknown_existence_means_tradable():
    step3 = REPO_ROOT / "scripts" / "phase22_step3_discovery_campaign.py"
    source = step3.read_text()
    assert "UNKNOWN_EXISTENCE means tradable" not in source
    assert "is_research_eligible" in source  # exclusion rule actually applied, not just documented


def test_no_phase22_file_declares_profitability():
    forbidden_patterns = ("is_profitable = True", "claimed_profitable", "profitability_confirmed")
    for path in _all_phase22_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to claim profitability via {pattern!r}"
