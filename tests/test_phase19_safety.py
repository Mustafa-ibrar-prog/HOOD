"""Phase 19 Final Safety Check: options-alpha DISCOVERY foundation only --
no live trading strategy, no order placement, no strategy-to-execution
connection, no alpha declared as fact, no fabricated/interpolated
historical options data, no prior-phase hypothesis/statistical-machinery
modification, no VALIDATION/FINAL_HOLDOUT data access.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE19_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase19_*.py"))
PHASE19_SRC_MODULES = [
    "src/options/universe.py",
    "src/options/moneyness.py",
    "src/options/expiration.py",
    "src/options/price_history.py",
    "src/options/contract_existence.py",
    "src/options/research_observation.py",
    "src/options/cost_model.py",
    "src/options/opportunity_score.py",
]
FORBIDDEN_IMPORT_PREFIXES = ("src.execution.gateway", "src.execution.live_client", "src.orchestrator")
FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order", "submit_order",
    "cancel_equity_order", "cancel_option_order", "review_option_order",
)


def _all_phase19_files():
    return [REPO_ROOT / rel for rel in PHASE19_SRC_MODULES] + list(PHASE19_SCRIPTS)


def test_no_phase19_file_imports_the_live_order_placement_path():
    for path in _all_phase19_files():
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


def test_no_phase19_file_references_a_live_order_placement_call():
    for path in _all_phase19_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_no_phase19_file_functionally_touches_a_prior_phase_hypothesis():
    prior_ids = (
        ("MR-002", "P7-VOLANOM-A", "P7-VOLANOM-A-DEV1", "P9-VOLCLUST-A")
        + tuple(f"P10-VP-{i:03d}" for i in range(1, 11))
        + tuple(f"P11-VCE-{i:03d}" for i in range(1, 7))
        + tuple(f"P12-CSRS-{i:03d}" for i in range(1, 11))
        + tuple(f"P13-OID-{i:03d}" for i in range(1, 9))
    )
    forbidden_patterns = tuple(f'"{hid}"' for hid in prior_ids) + tuple(f"'{hid}'" for hid in prior_ids)
    for path in _all_phase19_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} references a prior-phase hypothesis id via {pattern!r}"


def test_phase19_hypothesis_family_is_new_and_self_contained():
    """Every P19-OPT-* hypothesis registered by step 2 must have
    parent_hypothesis_id=None -- this is a NEW family, not a
    'development' translation of a prior discovery hypothesis (that
    distinction, per src.research.hypothesis's docstring, is reserved
    for a genuinely different kind of follow-on work this phase does not
    do)."""
    step2 = REPO_ROOT / "scripts" / "phase19_step2_preregister_hypotheses.py"
    assert step2.is_file()
    source = step2.read_text()
    assert "parent_hypothesis_id=None" in source
    assert "family=\"options_alpha\"" in source


def test_no_phase19_file_declares_alpha_as_fact():
    """Part 20's explicit prohibition: no Phase 19 script may claim a
    strategy is profitable, validated, or ready to trade -- only
    DISCOVERY_SUPPORTED/REJECTED/INCONCLUSIVE/FRAGILE/NOT_READY
    classifications, which are discovery-stage labels, not trading
    claims."""
    forbidden_patterns = ("is_profitable=True", "strategy_validated=True", "ready_to_trade=True", "PRODUCTION_READY")
    for path in _all_phase19_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to declare alpha as fact via {pattern!r}"


def test_no_phase19_file_fabricates_or_interpolates_historical_options_data():
    forbidden_patterns = (
        "interpolate(", "np.interp", "synthetic_quote", "fabricated_quote", "assumed_iv", "assumed_bid",
        "assumed_ask", "manufactured_greeks", "reconstruct_historical",
    )
    for path in _all_phase19_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate/interpolate historical options data via {pattern!r}"


def test_no_phase19_file_touches_development_validation_or_final_holdout_data():
    for path in PHASE19_SCRIPTS:
        source = path.read_text()
        assert "PartitionLifecycleStage.VALIDATION" not in source
        assert "PartitionLifecycleStage.FINAL_HOLDOUT" not in source
        assert "PartitionLifecycleStage.DEVELOPMENT" not in source


def test_no_phase19_file_purchases_or_subscribes():
    forbidden_patterns = ("subscribe(", "create_account(", "purchase(", "api_key=", "API_KEY=")
    for path in _all_phase19_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} references {pattern!r} -- no paid subscription/account may be created this phase"


def test_no_live_or_paper_trading_enabled_by_this_phase():
    forbidden_patterns = ("live_trading_confirmed=True", "live_auto_execute=True", "trading_mode=\"live\"", "trading_mode='live'")
    for path in _all_phase19_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to enable live/paper trading via {pattern!r}"


def test_cost_model_never_claims_execution_realistic_research_was_produced():
    """Part 10's central constraint, made mechanical: no Phase 19 file
    may assert `ResearchRealismLabel.EXECUTION_REALISTIC_RESEARCH` was
    actually USED to label a result -- it may only be named (e.g. in a
    docstring or as an enum member) to document why it is unavailable."""
    forbidden = "= ResearchRealismLabel.EXECUTION_REALISTIC_RESEARCH"
    for path in _all_phase19_files():
        if not path.is_file():
            continue
        assert forbidden not in path.read_text(), f"{path} appears to assign the EXECUTION_REALISTIC_RESEARCH label to a real result"


def test_opportunity_score_module_computes_no_default_composite_score():
    """Static guarantee backing Part 11: OpportunityScore's own default
    must be the NOT_COMPUTED_THIS_PHASE placeholder, not a real method
    name -- proves no scoring function was silently wired up."""
    source = (REPO_ROOT / "src" / "options" / "opportunity_score.py").read_text()
    assert 'scoring_method: str = "NOT_COMPUTED_THIS_PHASE"' in source
