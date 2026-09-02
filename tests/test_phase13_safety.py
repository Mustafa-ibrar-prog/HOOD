"""Phase 13 Final Safety Check: DISCOVERY_DATA-only access, no live/paper
orders, MR-002/P7/P9/every P10-VP-*/every P11-VCE-*/every P12-CSRS-*
hypothesis untouched, gate stays below PAPER_TRADING_ELIGIBLE for every
P13-OID-* hypothesis (and never reaches DEVELOPMENT_* at all — Part 30:
this phase STOPS after discovery), no hidden optimization, no contaminated
OHLC construction / adjusted-unadjusted price mixing.

Mirrors tests/test_phase8_safety.py / test_phase9_safety.py /
test_phase10_safety.py / test_phase11_safety.py / test_phase12_safety.py's
exact pattern for the Phase 13 surface area.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from src.research.discovery_development_gate import CODE_COMPUTABLE_STAGES, DiscoveryDevelopmentStage
from src.research.hypothesis import Hypothesis, HypothesisRegistry
from src.research.preregistration import PreregistrationError, PreregistrationStore, require_preregistered

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE13_SRC_MODULES = [
    "src/features/overnight_intraday.py",
    "src/research/overnight_intraday_targets.py",
]
PHASE13_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase13_*.py"))
FORBIDDEN_IMPORT_PREFIXES = ("src.execution", "src.orchestrator")
FORBIDDEN_CALLS = ("place_equity_order", "place_option_order", "place_crypto_order", "submit_order", "cancel_equity_order", "cancel_option_order")
P13_HYPOTHESIS_IDS = tuple(f"P13-OID-{i:03d}" for i in range(1, 9))


def _all_phase13_files():
    return [REPO_ROOT / rel for rel in PHASE13_SRC_MODULES] + list(PHASE13_SCRIPTS)


def test_no_phase13_module_imports_the_live_execution_or_orchestrator_path():
    for path in _all_phase13_files():
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


def test_no_phase13_module_references_a_live_order_placement_call():
    for path in _all_phase13_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_no_phase13_script_functionally_touches_mr002():
    forbidden_functional_patterns = ('FrozenStrategyStore', 'src.research.frozen_strategy', 'hypothesis_id="MR-002"', "hypothesis_id='MR-002'", 'strategy_id="MR-002"', "strategy_id='MR-002'", '.get("MR-002"', ".get('MR-002'")
    for path in PHASE13_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_functional_patterns:
            assert pattern not in source, f"{path} functionally references MR-002 via {pattern!r}"


def test_no_phase13_script_touches_development_validation_or_final_holdout_data():
    """Static guarantee: no Phase 13 script references DEVELOPMENT_DATA,
    VALIDATION_DATA, or FINAL_HOLDOUT_DATA partitions by name — only
    PartitionLifecycleStage.DISCOVERY may appear (Part 21, 30)."""
    for path in PHASE13_SCRIPTS:
        source = path.read_text()
        assert "PartitionLifecycleStage.VALIDATION" not in source
        assert "PartitionLifecycleStage.FINAL_HOLDOUT" not in source
        assert "PartitionLifecycleStage.DEVELOPMENT" not in source


def test_no_phase13_script_writes_to_a_prior_phase_hypothesis():
    """P7-VOLANOM-A, P7-VOLANOM-A-DEV1, P9-VOLCLUST-A, every P10-VP-*
    hypothesis, every P11-VCE-* hypothesis, and every P12-CSRS-* hypothesis
    may only be READ this phase."""
    prior_ids = (
        ("P7-VOLANOM-A", "P7-VOLANOM-A-DEV1", "P9-VOLCLUST-A")
        + tuple(f"P10-VP-{i:03d}" for i in range(1, 11))
        + tuple(f"P11-VCE-{i:03d}" for i in range(1, 7))
        + tuple(f"P12-CSRS-{i:03d}" for i in range(1, 11))
    )
    forbidden_write_patterns = tuple(f'gate_store.transition(hypothesis_id="{hid}"' for hid in prior_ids) + \
        tuple(f"gate_store.transition(hypothesis_id='{hid}'" for hid in prior_ids) + ("hyp_registry.register(parent)",)
    for path in PHASE13_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_write_patterns:
            assert pattern not in source, f"{path} appears to write to a prior-phase hypothesis via {pattern!r}"


def test_discovery_development_stage_is_capped_for_code():
    assert DiscoveryDevelopmentStage.PAPER_TRADING_ELIGIBLE in CODE_COMPUTABLE_STAGES
    assert DiscoveryDevelopmentStage.HUMAN_APPROVAL not in CODE_COMPUTABLE_STAGES
    assert DiscoveryDevelopmentStage.PAPER_TRADING not in CODE_COMPUTABLE_STAGES
    assert DiscoveryDevelopmentStage.LIVE_TRADING not in CODE_COMPUTABLE_STAGES


def test_phase13_scripts_never_reach_development_stage_or_beyond():
    """Static guarantee (Part 30 — STOP after discovery, do not proceed
    to development): no Phase 13 script references any DEVELOPMENT_*,
    VALIDATION, HOLDOUT, PAPER_TRADING_ELIGIBLE, HUMAN_APPROVAL,
    PAPER_TRADING, LIVE_ELIGIBLE, or LIVE_TRADING stage."""
    forbidden_stage_names = (
        "DEVELOPMENT_PREREGISTERED", "DEVELOPMENT_TESTED", "DEVELOPMENT_SUPPORTED",
        "VALIDATION", "HOLDOUT", "PAPER_TRADING_ELIGIBLE", "HUMAN_APPROVAL", "PAPER_TRADING", "LIVE_ELIGIBLE", "LIVE_TRADING",
    )
    for path in PHASE13_SCRIPTS:
        source = path.read_text()
        for stage in forbidden_stage_names:
            assert f"DiscoveryDevelopmentStage.{stage}" not in source, f"{path} references DiscoveryDevelopmentStage.{stage}"


def test_no_phase13_script_creates_a_backtest_or_trading_strategy():
    """Part 30: no development/backtesting of any P13 hypothesis this
    phase — no BacktestEngine/run_research_backtest usage anywhere."""
    forbidden_patterns = ("BacktestEngine(", "run_research_backtest(", "class OvernightIntradayStrategy", "PositionSizer(")
    for path in PHASE13_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to run a backtest or define a trading strategy: {pattern!r}"


def test_no_phase13_script_mixes_adjusted_and_unadjusted_prices():
    """Part 2/22/30 — 'Do not mix adjusted close with unadjusted open' and
    'No adjusted/unadjusted price mixing'. Static guarantee: no Phase 13
    script references a second, differently-adjusted data source (e.g. a
    raw/unadjusted-suffixed store) alongside the single HistoricalDataStore
    used throughout — every OHLC value comes from the same store/bars, so
    open and close are always drawn from the same adjustment regime."""
    forbidden_patterns = ("adjustment_type=\"none\"", "adjustment_type='none'", "unadjusted_store", "raw_store", "HistoricalDataStore(", )
    for path in PHASE13_SCRIPTS:
        source = path.read_text()
        # HistoricalDataStore(...) constructed more than once in a script would suggest mixing two stores;
        # phase13_step0 legitimately constructs it once to inspect the universe, phase13_step2 once to build
        # the discovery panel. Guard against a SECOND distinct construction only.
        assert source.count("HistoricalDataStore(") <= 1, f"{path} constructs more than one HistoricalDataStore — possible adjusted/unadjusted price mixing"
        for pattern in forbidden_patterns[:-1]:
            assert pattern not in source, f"{path} references {pattern!r} (possible unadjusted price source)"


def test_no_phase13_script_silently_fills_missing_ohlc():
    """Part 22: 'Do not silently fill missing OHLC values.' Static
    guarantee: no Phase 13 script calls a forward-fill/interpolation
    helper on OHLC data; missing values must propagate as None and be
    excluded, never manufactured."""
    forbidden_patterns = ("fillna(", "ffill(", "bfill(", "interpolate(")
    for path in PHASE13_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to silently fill missing data via {pattern!r}"


# --- preregistration requirement -----------------------------------------------------------


@pytest.mark.parametrize("hyp_id", P13_HYPOTHESIS_IDS + ("P13-OID-FAMILY",))
def test_p13_hypothesis_cannot_run_without_preregistration(tmp_path, hyp_id):
    store = PreregistrationStore(tmp_path / "prereg.jsonl")
    with pytest.raises(PreregistrationError):
        require_preregistered(store, hyp_id)


def test_p13_hypothesis_runs_once_preregistered(tmp_path):
    from datetime import datetime, timezone

    from src.research.preregistration import PreregistrationRecord

    store = PreregistrationStore(tmp_path / "prereg.jsonl")
    store.register(PreregistrationRecord(
        hypothesis_id="P13-OID-001", hypothesis_version="1.0", rationale="r", expected_direction="positive",
        target_definition="next_close_to_close_return", features=("overnight_return",), universe_name="U", time_horizon_bars=1,
        parameter_ranges={}, validation_methodology="m", cost_assumptions="c", success_criteria=(), falsification_criteria=(),
        registered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    ))
    record = require_preregistered(store, "P13-OID-001")
    assert record.hypothesis_id == "P13-OID-001"


def test_p13_hypotheses_have_no_parent(tmp_path):
    registry = HypothesisRegistry(tmp_path / "hyps.jsonl")
    p13 = Hypothesis(
        hypothesis_id="P13-OID-001", name="p13", description="d", economic_intuition="e", mathematical_definition="m",
        required_data=(), required_features=(), prediction_horizon_bars=1, test_methodology="t", expected_direction="positive",
        assumptions=(), parent_hypothesis_id=None, development_version=None,
    )
    registry.register(p13)
    loaded = registry.get("P13-OID-001")
    assert loaded.parent_hypothesis_id is None  # a genuinely NEW family


def test_the_actual_phase13_gate_transitions_file_never_mentions_mr002_or_prior_phase_hypotheses():
    path = Path("logs/research_data/phase13_gate_transitions.jsonl")
    if not path.is_file():
        pytest.skip("phase13_gate_transitions.jsonl not present in this environment")
    prior_ids = ({"MR-002", "P7-VOLANOM-A", "P7-VOLANOM-A-DEV1", "P9-VOLCLUST-A"}
                 | {f"P10-VP-{i:03d}" for i in range(1, 11)}
                 | {f"P11-VCE-{i:03d}" for i in range(1, 7)}
                 | {f"P12-CSRS-{i:03d}" for i in range(1, 11)})
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        assert record.get("hypothesis_id") not in prior_ids


def test_the_actual_phase13_gate_transitions_file_never_exceeds_discovery_supported():
    """Data-level check: no recorded transition in the real Phase 13 gate
    log ever reaches DEVELOPMENT_* or beyond (Part 30's explicit stop)."""
    path = Path("logs/research_data/phase13_gate_transitions.jsonl")
    if not path.is_file():
        pytest.skip("phase13_gate_transitions.jsonl not present in this environment")
    allowed = {"IDEA", "PREREGISTERED", "DISCOVERY_TESTED", "DISCOVERY_SUPPORTED", "NOT_READY"}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        assert record.get("to_stage") in allowed, f"unexpected stage reached: {record.get('to_stage')}"
