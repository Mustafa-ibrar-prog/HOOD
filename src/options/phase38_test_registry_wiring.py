"""Phase 38, Part 8 — every statistical test this phase performs is
registered through Phase 33's EXISTING `TestRegistry`
(`src.options.phase33_test_registry`), reused completely unchanged.
Never an unregistered significance claim.

Family assignment follows Phase 33's own established convention
exactly: `PRIMARY_FAMILY` for the underlying-vs-option edge test (the
one direct "does this feature/implementation predict this target"
claim this phase makes), `DIAGNOSTIC_FAMILY` for robustness checks with
no well-defined null-hypothesis p-value of their own (leave-one-out,
parameter-neighborhood, concentration), `PLACEBO_FAMILY` for every
placebo/shuffled-feature/randomized-signal empirical p-value.
"""

from __future__ import annotations

from src.options.phase33_test_registry import (
    DIAGNOSTIC_FAMILY,
    PLACEBO_FAMILY,
    PRIMARY_FAMILY,
    InferentialTestRecord,
    TestRegistry,
)
from src.options.phase38_falsification import OutcomeStats, PlaceboResult, TimingRobustnessResult
from src.options.phase38_underlying_vs_option_edge import UnderlyingVsOptionEdgeResult

STRATEGY_ID = "MOMENTUM_BREAKOUT_EXISTING_V1"


def register_edge_result(registry: TestRegistry, result: UnderlyingVsOptionEdgeResult, *, horizon_label: str) -> None:
    registry.register(InferentialTestRecord(
        hypothesis_id=STRATEGY_ID, feature_family="phase38_option_implementation_edge", feature="option_minus_underlying_return",
        target=f"executable_return_{horizon_label}", horizon=0, aggregation_method="paired_t_test",
        bucket_definition="contract_level", underlying="ALL", test_type="paired_t_test_p", sample_size=result.n_outcomes,
        p_value=result.excess_return_p_value, effect_size=result.mean_excess_return, correction_family=PRIMARY_FAMILY,
    ))


def register_placebo_result(registry: TestRegistry, result: PlaceboResult, *, horizon_label: str) -> None:
    registry.register(InferentialTestRecord(
        hypothesis_id=STRATEGY_ID, feature_family="phase38_falsification", feature=result.method,
        target=f"executable_return_{horizon_label}", horizon=0, aggregation_method=f"placebo:{result.method}",
        bucket_definition="contract_level", underlying="ALL", test_type="placebo_empirical_p", sample_size=result.n_observed,
        p_value=result.empirical_p_value, effect_size=result.observed_statistic, correction_family=PLACEBO_FAMILY,
    ))


def register_timing_robustness_result(registry: TestRegistry, result: TimingRobustnessResult, *, horizon_label: str) -> None:
    registry.register(InferentialTestRecord(
        hypothesis_id=STRATEGY_ID, feature_family="phase38_falsification", feature=result.method,
        target=f"executable_return_{horizon_label}", horizon=0, aggregation_method=result.method,
        bucket_definition="contract_level", underlying="ALL", test_type="mean_return_shift", sample_size=result.n_recomputed,
        p_value=None, effect_size=result.recomputed_mean_return, correction_family=DIAGNOSTIC_FAMILY,
    ))


def register_leave_one_out_results(registry: TestRegistry, results: dict[str, OutcomeStats], *, method: str, horizon_label: str) -> None:
    for key, stats in results.items():
        registry.register(InferentialTestRecord(
            hypothesis_id=STRATEGY_ID, feature_family="phase38_falsification", feature=f"{method}:{key}",
            target=f"executable_return_{horizon_label}", horizon=0, aggregation_method=method,
            bucket_definition="contract_level", underlying=key if method == "leave_one_symbol_out" else "ALL",
            test_type="mean_return_excluding_group", sample_size=stats.n, p_value=stats.p_value_vs_zero,
            effect_size=stats.mean_return, correction_family=DIAGNOSTIC_FAMILY,
        ))
