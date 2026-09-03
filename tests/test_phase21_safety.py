"""Phase 21 Final Safety Check (Part 25): adversarial falsification only
-- no live/paper order, no execution-layer import from research, no
FINAL_HOLDOUT/VALIDATION access, no re-registration of the frozen
P19-OPT-005/P19-OPT-009 parent definitions, deterministic experiment
fingerprints, no fabricated historical IV/Greeks/volume/OI/bid-ask, no
future-data or future-contract-existence leakage, no hypothesis declared
VALIDATED (Phase 21's vocabulary is REJECTED/FRAGILE/INCONCLUSIVE/
ROBUST_DISCOVERY_CANDIDATE -- explicitly NOT "validated").
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE21_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase21_*.py"))
PHASE21_SRC_MODULES = [
    "src/options/placebo_extensions.py",
    "src/options/outlier_treatment.py",
    "src/options/dependence_bootstrap.py",
]
FORBIDDEN_IMPORT_PREFIXES = ("src.execution.gateway", "src.execution.live_client", "src.orchestrator")
FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order", "submit_order",
    "cancel_equity_order", "cancel_option_order", "review_option_order", "review_equity_order",
)


def _all_phase21_files():
    return [REPO_ROOT / rel for rel in PHASE21_SRC_MODULES] + list(PHASE21_SCRIPTS)


def test_phase21_files_exist():
    assert PHASE21_SCRIPTS, "expected at least the step1/step2 Phase 21 scripts to exist"
    for rel in PHASE21_SRC_MODULES:
        assert (REPO_ROOT / rel).is_file(), f"missing {rel}"


def test_no_phase21_file_imports_the_live_order_placement_path():
    for path in _all_phase21_files():
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


def test_no_phase21_file_references_a_live_or_paper_order_placement_call():
    for path in _all_phase21_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_no_phase21_file_creates_a_strategy_object():
    """Part 24: even a strong-looking candidate must not be connected to
    a live/paper strategy this phase."""
    forbidden_patterns = ("LiveStrategy(", "PaperStrategy(", "StrategyExecutor(", "connect_alpha_to_execution")
    for path in _all_phase21_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to create/connect a strategy via {pattern!r}"


def test_no_phase21_file_modifies_the_frozen_parent_or_candidate_definitions():
    """Part 2/4's explicit instruction: P19-OPT-005, P19-OPT-009, and
    their -EXPANDED children are READ (hyp_registry.get(...)) to verify
    they are frozen, but never re-registered/edited with new content this
    phase."""
    for path in PHASE21_SCRIPTS:
        source = path.read_text()
        for hid in ("P19-OPT-005", "P19-OPT-009", "P19-OPT-005-EXPANDED", "P19-OPT-009-EXPANDED"):
            assert f'hypothesis_id="{hid}", name=' not in source, f"{path} appears to re-register {hid}"


def test_no_phase21_file_declares_a_hypothesis_validated():
    """Part 23's explicit vocabulary rule: REJECTED / FRAGILE /
    INCONCLUSIVE / ROBUST_DISCOVERY_CANDIDATE only -- never "VALIDATED",
    and ROBUST_DISCOVERY_CANDIDATE itself must never be equated with
    validated in an assignment/return (docstrings/comments explaining the
    prohibition are fine)."""
    forbidden_patterns = (
        'verdict = "VALIDATED"', 'verdict == "VALIDATED"', 'classification = "VALIDATED"', 'return "VALIDATED"',
        'final = "VALIDATED"',
    )
    for path in _all_phase21_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to declare a hypothesis VALIDATED via {pattern!r}"


def test_robust_discovery_candidate_classification_is_documented_as_not_validated():
    step2 = REPO_ROOT / "scripts" / "phase21_step2_falsification_campaign.py"
    assert step2.is_file()
    source = step2.read_text()
    assert "ROBUST_DISCOVERY_CANDIDATE" in source
    assert "does NOT mean validated" in source or "does not mean validated" in source.lower()


def test_no_phase21_file_touches_development_validation_or_final_holdout_data():
    for path in PHASE21_SCRIPTS:
        source = path.read_text()
        assert "PartitionLifecycleStage.VALIDATION" not in source
        assert "PartitionLifecycleStage.FINAL_HOLDOUT" not in source
        assert "PartitionLifecycleStage.DEVELOPMENT" not in source


def test_no_phase21_file_uses_a_live_only_field_as_historical():
    forbidden_patterns = (
        "historical_bid", "historical_ask", "historical_open_interest", "historical_iv",
        "current_open_interest_as_historical", "assumed_historical_liquidity_score",
    )
    for path in _all_phase21_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate a historical liquidity field via {pattern!r}"


def test_no_phase21_file_fabricates_or_interpolates_historical_options_data():
    forbidden_patterns = (
        "interpolate(", "np.interp", "synthetic_quote", "fabricated_quote", "assumed_iv", "assumed_bid",
        "assumed_ask", "manufactured_greeks", "reconstruct_historical",
    )
    for path in _all_phase21_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate/interpolate historical options data via {pattern!r}"


def test_no_phase21_file_reconstructs_and_pretends_to_observe_greeks():
    """Part 15's explicit instruction: 'Do not use future Greeks.
    Historical Greeks are unavailable... Do not reconstruct Greeks and
    pretend they were observed.' Any Greeks-adjacent analysis must be
    explicitly labeled HISTORICAL_GREEKS_UNAVAILABLE, not silently
    computed."""
    step2 = REPO_ROOT / "scripts" / "phase21_step2_falsification_campaign.py"
    source = step2.read_text()
    assert "HISTORICAL_GREEKS_UNAVAILABLE" in source
    forbidden_patterns = ("reconstructed_delta", "assumed_delta", "fabricated_greeks", "synthetic_delta")
    for pattern in forbidden_patterns:
        assert pattern not in source, f"{step2} appears to reconstruct Greeks via {pattern!r}"


def test_no_phase21_file_purchases_or_subscribes():
    forbidden_patterns = ("subscribe(", "create_account(", "purchase(", "api_key=", "API_KEY=")
    for path in _all_phase21_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} references {pattern!r} -- no paid subscription/account may be created this phase"


def test_no_live_or_paper_trading_enabled_by_this_phase():
    forbidden_patterns = ("live_trading_confirmed=True", "live_auto_execute=True", "trading_mode=\"live\"", "trading_mode='live'")
    for path in _all_phase21_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to enable live/paper trading via {pattern!r}"


def test_cost_model_never_claims_execution_realistic_research_was_produced():
    forbidden = "= ResearchRealismLabel.EXECUTION_REALISTIC_RESEARCH"
    for path in _all_phase21_files():
        if not path.is_file():
            continue
        assert forbidden not in path.read_text(), f"{path} appears to assign the EXECUTION_REALISTIC_RESEARCH label to a real result"


def test_step1_computes_a_deterministic_experiment_fingerprint():
    step1 = REPO_ROOT / "scripts" / "phase21_step1_verify_frozen_definitions.py"
    assert step1.is_file()
    source = step1.read_text()
    assert "compute_experiment_fingerprint" in source
    assert "ExperimentDimensions" in source


def test_placebo_extensions_module_never_duplicates_the_phase7_ic_helpers_signature_incorrectly():
    """Every new IC-based placebo function must actually call
    compute_ic_series/summarize_ic (reused, not reimplemented) -- a
    lightweight structural guard against silently forking the IC math."""
    source = (REPO_ROOT / "src/options/placebo_extensions.py").read_text()
    assert "from src.research.ic import compute_ic_series, summarize_ic" in source
    assert "def compute_ic_series(" not in source  # never reimplemented locally
    assert "def spearman_correlation(" not in source


def test_no_phase21_file_declares_profitability():
    """Part 24: 'DO NOT claim profitability.'"""
    forbidden_patterns = ("is_profitable = True", "claimed_profitable", "profitability_confirmed")
    for path in _all_phase21_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to claim profitability via {pattern!r}"


def test_no_phase21_file_tunes_hypothesis_parameters_to_its_own_results():
    """Part 24: 'DO NOT... tune the hypothesis to Phase 21 results.' A
    crude but real guard: the frozen candidates' feature/target/horizon
    values must never be reassigned mid-script based on a computed
    result (only ever read from the frozen CANDIDATES config or the
    hypothesis registry)."""
    step2 = REPO_ROOT / "scripts" / "phase21_step2_falsification_campaign.py"
    source = step2.read_text()
    forbidden_patterns = ("best_feature =", "optimal_parameter =", "tuned_horizon =", "grid_search(")
    for pattern in forbidden_patterns:
        assert pattern not in source, f"{step2} appears to tune a parameter to its own results via {pattern!r}"
