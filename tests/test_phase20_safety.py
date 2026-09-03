"""Phase 20 Final Safety Check: universe expansion and replication only
-- no live/paper order, no strategy-to-execution connection, no
hypothesis declared VALIDATED, no fabricated/interpolated historical
data, no live-only field used as historical, no Phase 19 hypothesis
definition modified, no VALIDATION/FINAL_HOLDOUT access.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE20_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase20_*.py"))
PHASE20_SRC_MODULES = [
    "src/options/research_eligibility.py",
    "src/options/expiration_diversity.py",
    "src/options/moneyness_diversity.py",
    "src/options/data_balance.py",
    "src/options/return_normalization.py",
    "src/options/mechanical_baseline.py",
]
FORBIDDEN_IMPORT_PREFIXES = ("src.execution.gateway", "src.execution.live_client", "src.orchestrator")
FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order", "submit_order",
    "cancel_equity_order", "cancel_option_order", "review_option_order",
)


def _all_phase20_files():
    return [REPO_ROOT / rel for rel in PHASE20_SRC_MODULES] + list(PHASE20_SCRIPTS)


def test_no_phase20_file_imports_the_live_order_placement_path():
    for path in _all_phase20_files():
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


def test_no_phase20_file_references_a_live_order_placement_call():
    for path in _all_phase20_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_no_phase20_file_modifies_a_prior_phase_hypothesis_definition():
    """Part 9's explicit instruction: the P19-OPT-* originals are read
    (to confirm they exist) but never edited or re-registered with new
    content -- only NEW P19-OPT-*-EXPANDED ids may be registered."""
    for path in PHASE20_SCRIPTS:
        source = path.read_text()
        for i in range(1, 13):
            hid = f"P19-OPT-{i:03d}"
            # The bare id may be READ (e.g. hyp_registry.get(hid)) but must never appear as a
            # freshly-registered hypothesis_id= kwarg (that would mean re-registering/editing it).
            assert f'hypothesis_id="{hid}", name=' not in source, f"{path} appears to re-register {hid}"


def test_phase20_replication_hypotheses_reference_a_parent():
    step3 = REPO_ROOT / "scripts" / "phase20_step3_preregister_replication.py"
    assert step3.is_file()
    source = step3.read_text()
    assert "parent_hypothesis_id=parent_id" in source
    for i in ("004", "005", "008", "009", "012"):
        assert f"P19-OPT-{i}-EXPANDED" in source


def test_no_phase20_file_declares_a_hypothesis_validated():
    """Part 23's explicit vocabulary rule: EXPANDED_DISCOVERY_SUPPORTED,
    never VALIDATED. Scripts may legitimately NAME "VALIDATED" in a
    docstring/comment to document the prohibition (e.g. 'never
    "VALIDATED"') -- only an actual ASSIGNMENT/classification form is
    forbidden."""
    forbidden_patterns = ('verdict = "VALIDATED"', "verdict == \"VALIDATED\"", "classification = \"VALIDATED\"", 'return "VALIDATED"')
    for path in _all_phase20_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to declare a hypothesis VALIDATED via {pattern!r}"


def test_no_phase20_file_uses_a_live_only_field_as_historical():
    """Part 2's explicit prohibitions: never treat live/current bid, ask,
    volume, open interest, or IV as if it were a historical observation."""
    forbidden_patterns = (
        "historical_bid", "historical_ask", "historical_open_interest", "historical_iv",
        "current_open_interest_as_historical", "assumed_historical_liquidity_score",
    )
    for path in _all_phase20_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate a historical liquidity field via {pattern!r}"


def test_no_phase20_file_fabricates_or_interpolates_historical_options_data():
    forbidden_patterns = (
        "interpolate(", "np.interp", "synthetic_quote", "fabricated_quote", "assumed_iv", "assumed_bid",
        "assumed_ask", "manufactured_greeks", "reconstruct_historical",
    )
    for path in _all_phase20_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate/interpolate historical options data via {pattern!r}"


def test_no_phase20_file_touches_development_validation_or_final_holdout_data():
    for path in PHASE20_SCRIPTS:
        source = path.read_text()
        assert "PartitionLifecycleStage.VALIDATION" not in source
        assert "PartitionLifecycleStage.FINAL_HOLDOUT" not in source
        assert "PartitionLifecycleStage.DEVELOPMENT" not in source


def test_no_phase20_file_purchases_or_subscribes():
    forbidden_patterns = ("subscribe(", "create_account(", "purchase(", "api_key=", "API_KEY=")
    for path in _all_phase20_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} references {pattern!r} -- no paid subscription/account may be created this phase"


def test_no_live_or_paper_trading_enabled_by_this_phase():
    forbidden_patterns = ("live_trading_confirmed=True", "live_auto_execute=True", "trading_mode=\"live\"", "trading_mode='live'")
    for path in _all_phase20_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to enable live/paper trading via {pattern!r}"


def test_cost_model_never_claims_execution_realistic_research_was_produced():
    forbidden = "= ResearchRealismLabel.EXECUTION_REALISTIC_RESEARCH"
    for path in _all_phase20_files():
        if not path.is_file():
            continue
        assert forbidden not in path.read_text(), f"{path} appears to assign the EXECUTION_REALISTIC_RESEARCH label to a real result"
