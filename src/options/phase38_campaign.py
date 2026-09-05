"""Phase 38 — the campaign orchestrator. Ties every module in this
phase together and runs against the REAL (as of this phase, empty)
Phase 37 stores. This is the single function the final report's numbers
come from — nothing in the report is computed ad hoc outside this
pipeline.

No live/paper order is ever created here — this module only reads from
Phase 37's stores and Phase 33/36's existing infrastructure, and never
imports anything execution-adjacent (verified by
`tests/test_phase38_safety.py`, the same static+dynamic pattern Phase
37 established).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src.options.phase33_test_registry import PRIMARY_FAMILY, TestRegistry, apply_correction
from src.options.phase38_affordability import ThousandDollarAffordabilityResult, evaluate_thousand_dollar_affordability
from src.options.phase38_causal_validation_dataset import CausalFeatureRow, build_causal_validation_dataset
from src.options.phase38_chronological_split import ChronologicalSplit, split_chronologically
from src.options.phase38_economic_validation import EconomicValidationReport, build_economic_validation_report
from src.options.phase38_falsification import (
    ConcentrationResult,
    OutlierAnalysisResult,
    concentration_analysis,
    cost_stress_test,
    leave_one_period_out,
    leave_one_symbol_out,
    outlier_removal_test,
    randomized_signal_placebo,
    shifted_signal_test,
    spread_stress_test,
)
from src.options.phase38_live_replication import LiveReplicationReport, evaluate_live_replication
from src.options.phase38_targets import DEFAULT_HORIZONS, ForwardHorizon, ForwardOutcome, compute_forward_outcome
from src.options.phase38_test_registry_wiring import register_edge_result, register_placebo_result, register_timing_robustness_result
from src.options.phase38_underlying_vs_option_edge import UnderlyingVsOptionEdgeResult, evaluate_underlying_vs_option_edge
from src.options.phase38_validation_gate import GateEvidence, GateResult, evaluate_validation_gate

if TYPE_CHECKING:
    from src.research_recorder.recorder import RecorderStores

DEFAULT_ACCOUNT_EQUITY_USD = 1000.0


@dataclass(frozen=True)
class Phase38CampaignResult:
    horizon: ForwardHorizon
    n_dataset_rows: int
    n_entry_signals: int
    n_outcomes: int
    chronological_split: ChronologicalSplit
    development_edge: UnderlyingVsOptionEdgeResult
    validation_edge: UnderlyingVsOptionEdgeResult
    holdout_edge: UnderlyingVsOptionEdgeResult
    economic_report: EconomicValidationReport
    affordability: ThousandDollarAffordabilityResult
    spread_stress_results: tuple
    cost_stress_results: tuple
    leave_one_period_out: dict
    leave_one_symbol_out: dict
    outlier_analysis: OutlierAnalysisResult
    concentration: ConcentrationResult
    live_replication: LiveReplicationReport
    test_registry: TestRegistry
    gate_result: GateResult


def _dataset_by_option(dataset: list[CausalFeatureRow]) -> dict[str, list[CausalFeatureRow]]:
    by_option: dict[str, list[CausalFeatureRow]] = {}
    for row in dataset:
        by_option.setdefault(row.option_id, []).append(row)
    for rows in by_option.values():
        rows.sort(key=lambda r: r.observation_timestamp)
    return by_option


def run_phase38_campaign(
    *, stores: "RecorderStores", account_equity_usd: float = DEFAULT_ACCOUNT_EQUITY_USD, horizon: ForwardHorizon = DEFAULT_HORIZONS[0],
) -> Phase38CampaignResult:
    dataset = build_causal_validation_dataset(raw_store=stores.raw, underlying_store=stores.underlying, option_store=stores.option)
    by_option = _dataset_by_option(dataset)

    signal_rows = stores.signal.load_all_raw_dicts()
    enter_signals = [r for r in signal_rows if r.get("decision") == "ENTER" and r.get("candidate_option_id")]
    entry_rows: list[CausalFeatureRow] = []
    for sig in enter_signals:
        for row in by_option.get(sig["candidate_option_id"], []):
            if row.observation_cycle_id == sig["observation_cycle_id"]:
                entry_rows.append(row)
                break

    outcomes: list[ForwardOutcome] = []
    for entry in entry_rows:
        later = [r for r in by_option.get(entry.option_id, []) if r.observation_timestamp > entry.observation_timestamp]
        outcomes.append(compute_forward_outcome(entry, later, horizon=horizon))

    # The candidate pool for the randomized-signal placebo: every row in
    # the dataset, treated as a hypothetical entry against its own later
    # observations -- reuses the SAME target-construction function, never
    # a different/fabricated pool.
    candidate_pool: list[ForwardOutcome] = []
    for row in dataset:
        later = [r for r in by_option.get(row.option_id, []) if r.observation_timestamp > row.observation_timestamp]
        candidate_pool.append(compute_forward_outcome(row, later, horizon=horizon))

    split = split_chronologically(outcomes)
    development_edge = evaluate_underlying_vs_option_edge(split.development)
    validation_edge = evaluate_underlying_vs_option_edge(split.validation)
    holdout_edge = evaluate_underlying_vs_option_edge(split.final_holdout)

    registry = TestRegistry()
    register_edge_result(registry, holdout_edge, horizon_label=horizon.label)

    placebo_result = randomized_signal_placebo(outcomes, candidate_pool)
    register_placebo_result(registry, placebo_result, horizon_label=horizon.label)

    timing_result = shifted_signal_test(entry_rows, by_option, horizon=horizon)
    register_timing_robustness_result(registry, timing_result, horizon_label=horizon.label)

    apply_correction(registry, PRIMARY_FAMILY)

    economic_report = build_economic_validation_report(outcomes)
    affordability = evaluate_thousand_dollar_affordability(outcomes, account_equity_usd=account_equity_usd)
    spread_stress = spread_stress_test(outcomes)
    cost_stress = cost_stress_test(outcomes)
    lopo = leave_one_period_out(outcomes)
    loso = leave_one_symbol_out(outcomes)
    outliers = outlier_removal_test(outcomes)
    expiration_by_option = {row.option_id: row.expiration.isoformat() for row in dataset if row.expiration is not None}
    concentration = concentration_analysis(outcomes, expiration_by_option_id=expiration_by_option)
    live_replication = evaluate_live_replication(stores=stores, dataset=dataset)

    evidence = GateEvidence(
        chronological_split=split, development_edge=development_edge, validation_edge=validation_edge,
        holdout_edge=holdout_edge, holdout_touched_before_freeze=False, test_registry=registry,
        economic_report=economic_report, spread_stress_results=spread_stress, cost_stress_results=cost_stress,
        leave_one_period_out=lopo, leave_one_symbol_out=loso, placebo_result=placebo_result,
        timing_robustness_result=timing_result, affordability=affordability, data_quality=live_replication.data_quality,
    )
    gate_result = evaluate_validation_gate(evidence)

    return Phase38CampaignResult(
        horizon=horizon, n_dataset_rows=len(dataset), n_entry_signals=len(entry_rows), n_outcomes=len(outcomes),
        chronological_split=split, development_edge=development_edge, validation_edge=validation_edge,
        holdout_edge=holdout_edge, economic_report=economic_report, affordability=affordability,
        spread_stress_results=spread_stress, cost_stress_results=cost_stress, leave_one_period_out=lopo,
        leave_one_symbol_out=loso, outlier_analysis=outliers, concentration=concentration,
        live_replication=live_replication, test_registry=registry, gate_result=gate_result,
    )


def default_recorder_stores(base_dir: Path) -> "RecorderStores":
    """Phase 37 never specified a deployment path for its stores (a real
    gap this phase's audit found -- see Part 1). This is Phase 38's own
    disclosed default, matching this project's `logs/research_data/`
    convention; a future phase should promote this into `Settings` if
    the recorder is ever actually scheduled."""
    from src.research_recorder.recorder import RecorderStores
    from src.research_recorder.storage import CycleLogStore, NormalizedOptionStore, NormalizedUnderlyingStore, RawObservationStore, ResearchSignalStore

    return RecorderStores(
        raw=RawObservationStore(base_dir / "raw_observations.jsonl"),
        underlying=NormalizedUnderlyingStore(base_dir / "normalized_underlying.jsonl"),
        option=NormalizedOptionStore(base_dir / "normalized_options.jsonl"),
        signal=ResearchSignalStore(base_dir / "research_signals.jsonl"),
        cycle_log=CycleLogStore(base_dir / "cycle_log.jsonl"),
    )
