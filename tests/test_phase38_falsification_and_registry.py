"""Phase 38, Part 8-9 — falsification suite and TestRegistry
accounting."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from src.options.phase33_test_registry import PLACEBO_FAMILY, PRIMARY_FAMILY, TestRegistry, apply_correction
from src.options.phase38_causal_validation_dataset import CausalFeatureRow
from src.options.phase38_falsification import (
    INSUFFICIENT_SAMPLE,
    concentration_analysis,
    cost_stress_test,
    execution_delay_test,
    leave_one_period_out,
    leave_one_symbol_out,
    outcome_stats,
    outlier_removal_test,
    parameter_neighborhood_test,
    randomized_signal_placebo,
    shifted_signal_test,
    shuffled_feature_association_test,
    spread_stress_test,
)
from src.options.phase38_targets import ForwardHorizon, ForwardOutcome, compute_forward_outcome
from src.options.phase38_test_registry_wiring import register_edge_result, register_placebo_result
from src.options.phase38_underlying_vs_option_edge import EdgeClassification, UnderlyingVsOptionEdgeResult


def _outcome(ret, symbol="AAPL", t=None):
    t = t or datetime(2026, 9, 1, tzinfo=timezone.utc)
    return ForwardOutcome(
        option_id=f"opt-{symbol}", underlying_symbol=symbol, horizon_label="5min", entry_cycle_id="c0",
        entry_timestamp=t, exit_cycle_id="c1", exit_timestamp=t + timedelta(minutes=5), entry_ask=1.0, entry_bid=0.95,
        exit_bid=1.0 + ret, exit_ask=1.05 + ret, mid_return_pct=ret, executable_return_pct=ret, mfe_pct=max(ret, 0),
        mae_pct=min(ret, 0), directional_outcome="UP" if ret > 0 else "DOWN", risk_adjusted_outcome=None,
        entry_underlying=100.0, exit_underlying=100.0, underlying_return_pct=0.0, option_minus_underlying_return_pct=ret,
        data_limited_reason=None,
    )


def _causal_row(t_minutes, bid, ask, *, option_id="opt-1", cycle_prefix="c"):
    return CausalFeatureRow(
        observation_cycle_id=f"{cycle_prefix}{t_minutes}", observation_timestamp=datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(minutes=t_minutes),
        underlying_symbol="AAPL", option_id=option_id, option_type="call", strike=230.0, expiration=None, dte=30,
        moneyness=0.0, underlying_last=230.0, underlying_bid=None, underlying_ask=None, underlying_midpoint=230.0,
        option_bid=bid, option_ask=ask, option_bid_size=5, option_ask_size=5, option_mark=(bid + ask) / 2, option_midpoint=(bid + ask) / 2,
        implied_volatility=0.3, delta=0.5, gamma=None, theta=None, vega=None, rho=None, open_interest=100, volume=50,
        contract_state="active", contract_tradability="tradable", field_provenance={}, raw_payload_fingerprint="fp",
    )


# --- outcome_stats -------------------------------------------------------------------------------


def test_outcome_stats_empty():
    stats = outcome_stats([])
    assert stats.n == 0 and stats.mean_return is None


def test_outcome_stats_basic():
    stats = outcome_stats([_outcome(0.1), _outcome(-0.05)])
    assert stats.n == 2
    assert stats.win_rate == 0.5


# --- randomized signal placebo ------------------------------------------------------------------


def test_randomized_placebo_insufficient_sample():
    result = randomized_signal_placebo([_outcome(0.1)] * 5, [_outcome(0.1)] * 100)
    assert result.classification == INSUFFICIENT_SAMPLE


def test_randomized_placebo_observed_exceeds_placebo_when_genuinely_better():
    random.seed(1)
    observed = [_outcome(0.20)] * 25  # strong, consistent
    pool = [_outcome(random.gauss(0.0, 0.05)) for _ in range(500)]  # noise around zero
    result = randomized_signal_placebo(observed, pool, n_trials=50, seed=1)
    assert result.classification == "OBSERVED_EXCEEDS_PLACEBO"
    assert result.empirical_p_value < 0.10


def test_randomized_placebo_not_distinguishable_when_observed_is_average():
    random.seed(2)
    pool = [_outcome(random.gauss(0.0, 0.05)) for _ in range(500)]
    observed = random.sample(pool, 25)  # literally drawn from the same distribution
    result = randomized_signal_placebo(observed, pool, n_trials=50, seed=2)
    assert result.classification == "OBSERVED_NOT_DISTINGUISHABLE_FROM_PLACEBO"


# --- shuffled feature association -----------------------------------------------------------------


def test_shuffled_feature_insufficient_sample():
    result = shuffled_feature_association_test([_outcome(0.1)] * 5, [0.1] * 5, feature_name="moneyness")
    assert result.classification == INSUFFICIENT_SAMPLE


def test_shuffled_feature_detects_real_association():
    random.seed(3)
    features = [random.uniform(-1, 1) for _ in range(100)]
    outcomes = [_outcome(f * 0.5 + random.gauss(0, 0.01)) for f in features]  # strong linear relationship
    result = shuffled_feature_association_test(outcomes, features, feature_name="moneyness", n_trials=200, seed=3)
    assert result.classification == "OBSERVED_EXCEEDS_PLACEBO"


def test_shuffled_feature_no_association_reported_honestly():
    random.seed(4)
    features = [random.uniform(-1, 1) for _ in range(100)]
    outcomes = [_outcome(random.gauss(0, 0.1)) for _ in features]  # no real relationship
    result = shuffled_feature_association_test(outcomes, features, feature_name="moneyness", n_trials=200, seed=4)
    assert result.classification == "OBSERVED_NOT_DISTINGUISHABLE_FROM_PLACEBO"


# --- shifted signal / execution delay --------------------------------------------------------------


def test_shifted_signal_insufficient_sample():
    entries = [_causal_row(0, 1.0, 1.05)]
    dataset_by_option = {"opt-1": [_causal_row(0, 1.0, 1.05), _causal_row(5, 1.05, 1.10)]}
    result = shifted_signal_test(entries, dataset_by_option, horizon=ForwardHorizon("5min", 5, 3))
    assert result.classification == INSUFFICIENT_SAMPLE


def test_execution_delay_test_runs_without_crashing_on_larger_sample():
    entries = []
    dataset_by_option = {}
    for i in range(25):
        option_id = f"opt-{i}"
        rows = [_causal_row(0, 1.0, 1.05, option_id=option_id, cycle_prefix=f"o{i}c"), _causal_row(5, 1.05, 1.10, option_id=option_id, cycle_prefix=f"o{i}c"), _causal_row(10, 1.10, 1.15, option_id=option_id, cycle_prefix=f"o{i}c")]
        dataset_by_option[option_id] = rows
        entries.append(rows[0])
    result = execution_delay_test(entries, dataset_by_option, horizon=ForwardHorizon("5min", 5, 3), delay_cycles=1)
    assert result.method == "execution_delay"
    assert result.classification in ("ROBUST_TO_SIGNAL_SHIFT", "SIGN_FLIPS_UNDER_SIGNAL_SHIFT", INSUFFICIENT_SAMPLE)


# --- cost / spread stress -------------------------------------------------------------------------


def test_spread_stress_degrades_return_as_multiplier_increases():
    observed = [_outcome(0.2)] * 25
    results = spread_stress_test(observed, multipliers=(1.0, 5.0))
    assert results[0].mean_return_after_cost >= results[1].mean_return_after_cost


def test_cost_stress_can_flip_survival_at_high_multiplier():
    observed = [_outcome(0.005)] * 25  # tiny edge, easily wiped out by cost
    results = cost_stress_test(observed, per_side_cost_pct=0.01, multipliers=(1.0, 5.0))
    assert results[0].survives in (True, False)
    assert results[1].survives is False


def test_cost_stress_insufficient_sample_reported():
    results = cost_stress_test([_outcome(0.1)] * 5)
    assert all(r.survives is None for r in results)


# --- leave-one-out ---------------------------------------------------------------------------------


def test_leave_one_symbol_out_excludes_correctly():
    outcomes = [_outcome(0.1, symbol="AAPL")] * 10 + [_outcome(-0.1, symbol="MSFT")] * 10
    result = leave_one_symbol_out(outcomes)
    assert result["AAPL"].n == 10  # excludes AAPL, leaves 10 MSFT
    assert result["MSFT"].n == 10


def test_leave_one_period_out_groups_by_month():
    jan = [_outcome(0.1, t=datetime(2026, 1, 15, tzinfo=timezone.utc))] * 10
    feb = [_outcome(-0.1, t=datetime(2026, 2, 15, tzinfo=timezone.utc))] * 10
    result = leave_one_period_out(jan + feb)
    assert set(result) == {"2026-01", "2026-02"}
    assert result["2026-01"].n == 10


# --- parameter neighborhood ------------------------------------------------------------------------


def test_parameter_neighborhood_never_changes_the_base_horizon_only_tolerance():
    entries = [_causal_row(0, 1.0, 1.05)]
    dataset_by_option = {"opt-1": [_causal_row(0, 1.0, 1.05), _causal_row(5, 1.05, 1.10)]}
    results = parameter_neighborhood_test(entries, dataset_by_option, base_horizon=ForwardHorizon("5min", 5, 3), tolerance_deltas=(-1.0, 0.0, 1.0))
    assert set(results) == {-1.0, 0.0, 1.0}


# --- outlier removal ---------------------------------------------------------------------------------


def test_outlier_removal_identifies_top_contributor():
    outcomes = [_outcome(2.0)] + [_outcome(0.01) for _ in range(99)]
    result = outlier_removal_test(outcomes)
    assert result.top1pct_contribution_fraction > 0.5  # the single 2.0 outcome dominates the 99 * 0.01 outcomes
    assert result.stats_excluding_top1pct.n == 99


def test_outlier_removal_empty():
    result = outlier_removal_test([])
    assert result.n == 0 and result.top1pct_contribution_fraction is None


# --- concentration --------------------------------------------------------------------------------


def test_concentration_analysis_flags_dominant_underlying():
    outcomes = [_outcome(0.1, symbol="AAPL")] * 90 + [_outcome(0.1, symbol="MSFT")] * 10
    result = concentration_analysis(outcomes)
    assert result.max_underlying_concentration_pct == 0.9


def test_concentration_analysis_empty():
    result = concentration_analysis([])
    assert result.max_underlying_concentration_pct is None


# --- TestRegistry wiring ---------------------------------------------------------------------------


def test_edge_result_registers_into_primary_family():
    registry = TestRegistry()
    result = UnderlyingVsOptionEdgeResult(25, 0.05, 0.0, 0.05, 0.01, EdgeClassification.OPTION_ADDS_VALUE, "x")
    register_edge_result(registry, result, horizon_label="5min")
    assert len(registry.by_family(PRIMARY_FAMILY)) == 1


def test_placebo_result_registers_into_placebo_family():
    registry = TestRegistry()
    result = randomized_signal_placebo([_outcome(0.1)] * 25, [_outcome(0.05)] * 100, n_trials=10)
    register_placebo_result(registry, result, horizon_label="5min")
    assert len(registry.by_family(PLACEBO_FAMILY)) == 1


def test_correction_runs_cleanly_over_registered_tests():
    registry = TestRegistry()
    result = UnderlyingVsOptionEdgeResult(25, 0.05, 0.0, 0.05, 0.01, EdgeClassification.OPTION_ADDS_VALUE, "x")
    register_edge_result(registry, result, horizon_label="5min")
    correction = apply_correction(registry, PRIMARY_FAMILY)
    assert correction.n_registered == 1
    assert correction.n_with_p_value == 1
