"""Phase 31, Parts 14 & 15/18 — discovery classification and the
Promising Finding Gate."""

from __future__ import annotations

from src.options.dependence_bootstrap import SymbolClusterBootstrapReport
from src.options.mechanical_baseline import BaselineClassification, MechanicalBaselineComparison
from src.options.phase31_affordability_liquidity import AffordabilityFilterReport, CostSensitivityResult, LiquidityReport
from src.options.phase31_classification import DiscoveryClassification, HypothesisEvidence, classify_hypothesis
from src.options.phase31_evidence import CrossSectionalEvidence, TimeSeriesEvidence
from src.options.phase31_gate import evaluate_gate
from src.options.phase31_robustness import RobustnessReport
from src.research.cross_sectional_placebo import CrossSectionalPlaceboResult
from src.research.ic import ICSummary
from src.research.quantile import QuantilePortfolioReport
from src.research.cross_sectional_alpha import CrossSectionalAlphaReport, WeightedPortfolioReturn


def _cs_evidence(*, applicable=True, average_ic=0.05, n_points=20, spread=0.02) -> CrossSectionalEvidence:
    if not applicable:
        return CrossSectionalEvidence("f", "t", False, "CROSS_SECTIONAL_IC_UNDEFINED", None)
    ic_summary = ICSummary(
        feature_name="f", target_name="t", points=(), average_ic=average_ic, median_ic=average_ic,
        ic_stdev=0.1, ic_information_ratio=average_ic / 0.1 if average_ic else None, positive_ic_fraction=0.6,
    )
    # Patch points count via a fresh dataclass replace since ICPoint list affects n_timestamps().
    from src.research.ic import ICPoint
    from datetime import datetime, timezone
    points = tuple(ICPoint(timestamp=datetime(2026, 1, 1 + i, tzinfo=timezone.utc), ic=average_ic, sample_count=5) for i in range(n_points))
    ic_summary = ICSummary(
        feature_name="f", target_name="t", points=points, average_ic=average_ic, median_ic=average_ic,
        ic_stdev=0.1, ic_information_ratio=None, positive_ic_fraction=0.6,
    )
    quantile_report = QuantilePortfolioReport(feature_name="f", target_name="t", quantiles=(), spread_q5_minus_q1=spread, is_monotonic=True, timestamps_used=n_points)
    report = CrossSectionalAlphaReport(
        ic_summary=ic_summary, ic_t_statistic=2.0, ic_p_value=0.01, quantile_report=quantile_report,
        weighted_portfolio=WeightedPortfolioReturn(weighting="equal", long_short_return=spread, timestamps_used=n_points),
    )
    return CrossSectionalEvidence("f", "t", True, "", report)


def _ts_evidence(applicable=True) -> TimeSeriesEvidence:
    return TimeSeriesEvidence(
        feature_col="f", target_col="t", horizon_bars=5, min_obs=15, min_independent_periods=5,
        n_contracts_evaluated=10, n_contracts_eligible=8 if applicable else 0, per_contract=(),
        pooled_spearman_mean=0.1 if applicable else None, sign_stable_fraction=0.8 if applicable else None,
        applicable=applicable, reason="",
    )


def _robustness(fragile=False, sign_flips_underlyings=False) -> RobustnessReport:
    return RobustnessReport(
        feature_col="f", target_col="t", by_year=(), by_underlying=(), by_expiration=(), by_moneyness_bucket=(),
        by_call_put=(), leave_one_underlying_out=(), sign_flips_across_years=False,
        sign_flips_across_underlyings=sign_flips_underlyings, sign_flips_across_expirations=False,
        sign_flips_across_moneyness=False, sign_flips_call_vs_put=False, fragile=fragile,
    )


def _bootstrap(excludes_zero=True) -> SymbolClusterBootstrapReport:
    return SymbolClusterBootstrapReport(
        n_resamples=200, seed=1, n_symbols=6, point_estimate=0.05, confidence_level=0.90,
        lower_bound=0.01 if excludes_zero else -0.02, upper_bound=0.09, resampled_values=(0.05,),
    )


def _placebo(separates=True) -> dict:
    return {"shuffled_signal_placebo": CrossSectionalPlaceboResult(
        method="shuffled_signal_placebo", n_trials=200, seed=1, observed_statistic=0.05,
        placebo_distribution=(0.01, 0.02), empirical_p_value=0.02 if separates else 0.8,
        what_was_randomized="x", what_was_preserved="y", what_was_destroyed="z",
    )}


def _baseline(classification) -> MechanicalBaselineComparison:
    return MechanicalBaselineComparison(feature_name="f", option_target="t", underlying_target="u", option_ic=0.05, underlying_ic=0.01, gap=0.04, classification=classification)


def _affordability() -> AffordabilityFilterReport:
    return AffordabilityFilterReport(n_rows=10, n_priced_rows=10, average_premium_usd=500.0, median_premium_usd=500.0, min_premium_usd=100.0, max_premium_usd=900.0, pct_affordable_with_account=0.8, account_equity_usd=1000.0, average_spread_cost_usd=10.0, average_capital_required_usd=500.0)


def _liquidity() -> LiquidityReport:
    return LiquidityReport(n_rows=10, pct_quote_available=0.9, average_spread_pct=0.02, average_volume=50.0, average_open_interest=200.0, execution_data_limited=False)


def _evidence(**overrides) -> HypothesisEvidence:
    base = dict(
        hypothesis_id="P31-OPT-001", feature_col="f", target_col="t", primary_horizon=5,
        cross_sectional=_cs_evidence(), time_series=_ts_evidence(), underlying_control=_baseline(BaselineClassification.OPTION_ADDS_INFORMATION),
        robustness=_robustness(), temporal_alignment=(), bootstrap=_bootstrap(), placebo_results=_placebo(),
        affordability=_affordability(), liquidity=_liquidity(),
        cost_sensitivity=(CostSensitivityResult(1.0, 0.02, 0.01, 0.01, True),),
        outlier_trimmed_ic=0.045, bh_significant=True, bh_adjusted_p=0.02,
    )
    base.update(overrides)
    return HypothesisEvidence(**base)


def test_not_ready_when_neither_evidence_type_applicable():
    evidence = _evidence(cross_sectional=_cs_evidence(applicable=False), time_series=_ts_evidence(applicable=False))
    result, _reason = classify_hypothesis(evidence)
    assert result == DiscoveryClassification.NOT_READY


def test_inconclusive_when_underpowered():
    evidence = _evidence(cross_sectional=_cs_evidence(n_points=3))
    result, _reason = classify_hypothesis(evidence)
    assert result == DiscoveryClassification.INCONCLUSIVE


def test_rejected_when_ic_tiny_and_not_significant():
    evidence = _evidence(cross_sectional=_cs_evidence(average_ic=0.001), bh_significant=False, placebo_results=_placebo(separates=False))
    result, _reason = classify_hypothesis(evidence)
    assert result == DiscoveryClassification.REJECTED


def test_inherited_from_underlying_overrides_significance():
    evidence = _evidence(underlying_control=_baseline(BaselineClassification.INHERITED_FROM_UNDERLYING))
    result, _reason = classify_hypothesis(evidence)
    assert result == DiscoveryClassification.INHERITED_FROM_UNDERLYING


def test_fragile_when_sign_flips_across_underlyings():
    evidence = _evidence(robustness=_robustness(fragile=True, sign_flips_underlyings=True))
    result, _reason = classify_hypothesis(evidence)
    assert result == DiscoveryClassification.FRAGILE


def test_fragile_when_bootstrap_crosses_zero():
    evidence = _evidence(bootstrap=_bootstrap(excludes_zero=False))
    result, _reason = classify_hypothesis(evidence)
    assert result == DiscoveryClassification.FRAGILE


def test_discovery_supported_when_everything_clears():
    evidence = _evidence()
    result, _reason = classify_hypothesis(evidence)
    assert result == DiscoveryClassification.DISCOVERY_SUPPORTED
    gate = evaluate_gate(evidence)
    assert gate.passed is True
    assert len(gate.criteria) == 12


def test_promising_when_significant_but_fails_cost():
    evidence = _evidence(cost_sensitivity=(CostSensitivityResult(1.0, 0.02, 0.05, -0.03, False),))
    result, _reason = classify_hypothesis(evidence)
    assert result == DiscoveryClassification.PROMISING
    gate = evaluate_gate(evidence)
    assert gate.passed is False
    assert "survives_reasonable_costs" in gate.failing_criteria


def test_gate_never_passes_with_a_single_failing_criterion():
    evidence = _evidence(placebo_results=_placebo(separates=False))
    gate = evaluate_gate(evidence)
    assert gate.passed is False
    assert "placebo_separation" in gate.failing_criteria


def test_gate_reports_all_twelve_named_criteria():
    evidence = _evidence()
    gate = evaluate_gate(evidence)
    names = {c.name for c in gate.criteria}
    assert names == {
        "preregistered", "causal", "survives_multiple_testing_correction", "economically_meaningful",
        "survives_reasonable_costs", "not_explained_by_underlying_control", "not_dependent_on_one_outlier",
        "reasonable_temporal_stability", "reasonable_symbol_stability", "placebo_separation",
        "bootstrap_support", "no_unresolved_major_leakage",
    }


def test_gate_fails_when_not_preregistered():
    evidence = _evidence()
    gate = evaluate_gate(evidence, is_preregistered=False)
    assert gate.passed is False
    assert "preregistered" in gate.failing_criteria
