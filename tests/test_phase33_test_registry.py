"""Phase 33, Part A/24 — the fixed multiple-testing accounting infrastructure."""

from __future__ import annotations

import pytest

from src.options.phase33_test_registry import (
    DIAGNOSTIC_FAMILY,
    PLACEBO_FAMILY,
    PRIMARY_FAMILY,
    InferentialTestRecord,
    TestRegistry,
    apply_correction,
    correlation_p_value,
)


def _record(hid, agg, underlying, target, p, effect=0.1, family=PRIMARY_FAMILY, n=50):
    return InferentialTestRecord(
        hypothesis_id=hid, feature_family="A", feature="f", target=target, horizon=5,
        aggregation_method=agg, bucket_definition="fine", underlying=underlying,
        test_type="spearman_correlation_p", sample_size=n, p_value=p, effect_size=effect,
        correction_family=family,
    )


def test_correlation_p_value_strong_correlation_significant():
    p = correlation_p_value(0.8, 50)
    assert p is not None
    assert p < 0.01


def test_correlation_p_value_zero_correlation_not_significant():
    p = correlation_p_value(0.01, 50)
    assert p is not None
    assert p > 0.5


def test_correlation_p_value_none_for_too_few_observations():
    assert correlation_p_value(0.5, 3) is None


def test_correlation_p_value_none_for_none_input():
    assert correlation_p_value(None, 50) is None


def test_registry_register_and_retrieve():
    reg = TestRegistry()
    r = _record("H1", "cross_sectional", "ALL", "t1", 0.01)
    reg.register(r)
    assert reg.all() == (r,)
    assert reg.by_hypothesis("H1") == (r,)


def test_registry_rejects_accidental_duplicate_registration():
    reg = TestRegistry()
    reg.register(_record("H1", "cross_sectional", "ALL", "t1", 0.01))
    with pytest.raises(ValueError):
        reg.register(_record("H1", "cross_sectional", "ALL", "t1", 0.02))


def test_registry_register_or_replace_allows_intentional_rerun():
    reg = TestRegistry()
    reg.register(_record("H1", "cross_sectional", "ALL", "t1", 0.01))
    reg.register_or_replace(_record("H1", "cross_sectional", "ALL", "t1", 0.02))
    assert len(reg.all()) == 1
    assert reg.all()[0].p_value == 0.02


def test_by_family_filters_correctly():
    reg = TestRegistry()
    reg.register(_record("H1", "cross_sectional", "ALL", "t1", 0.01, family=PRIMARY_FAMILY))
    reg.register(_record("H1", "leave_one_symbol_out", "AAPL", "t1", None, family=DIAGNOSTIC_FAMILY))
    reg.register(_record("H1", "placebo:shuffled_signal_placebo", "ALL", "t1", 0.3, family=PLACEBO_FAMILY))
    assert len(reg.by_family(PRIMARY_FAMILY)) == 1
    assert len(reg.by_family(DIAGNOSTIC_FAMILY)) == 1
    assert len(reg.by_family(PLACEBO_FAMILY)) == 1


def test_apply_correction_multiple_aggregation_methods_all_counted():
    """The Phase 32 gap this module fixes: pooled + per-symbol + cross-
    sectional tests for the SAME hypothesis must ALL enter the same
    correction family, not just the cross-sectional one."""
    reg = TestRegistry()
    reg.register(_record("H1", "cross_sectional", "ALL", "t1", 0.001))
    reg.register(_record("H1", "pooled_time_series", "ALL", "t1", 0.02))
    reg.register(_record("H1", "per_symbol", "AAPL", "t1", 0.5))
    reg.register(_record("H1", "per_symbol", "GOOG", "t1", 0.9))
    result = apply_correction(reg, PRIMARY_FAMILY)
    assert result.n_registered == 4
    assert result.n_with_p_value == 4
    assert result.bonferroni.n_tests == 4


def test_apply_correction_never_silently_drops_untestable_records():
    reg = TestRegistry()
    reg.register(_record("H1", "cross_sectional", "ALL", "t1", 0.01))
    reg.register(_record("H1", "symbol_balanced", "ALL", "t1", None))  # no formal p-value -- averaged correlation
    result = apply_correction(reg, PRIMARY_FAMILY)
    assert result.n_registered == 2
    assert result.n_with_p_value == 1  # only the cross-sectional one is testable
    updated = reg.by_family(PRIMARY_FAMILY)
    statuses = {r.aggregation_method: r.correction_status for r in updated}
    assert statuses["symbol_balanced"] == "NOT_APPLICABLE_NO_PVALUE"
    assert statuses["cross_sectional"] in ("SIGNIFICANT_AFTER_BH", "NOT_SIGNIFICANT_AFTER_BH")


def test_apply_correction_updates_registry_in_place():
    reg = TestRegistry()
    reg.register(_record("H1", "cross_sectional", "ALL", "t1", 0.0001))
    apply_correction(reg, PRIMARY_FAMILY)
    record = reg.by_hypothesis("H1")[0]
    assert record.correction_status != "PENDING"


def test_apply_correction_empty_family_returns_zero_counts():
    reg = TestRegistry()
    result = apply_correction(reg, PRIMARY_FAMILY)
    assert result.n_registered == 0
    assert result.n_with_p_value == 0
    assert result.bonferroni is None


def test_diagnostic_and_placebo_families_never_pollute_primary_correction():
    reg = TestRegistry()
    reg.register(_record("H1", "cross_sectional", "ALL", "t1", 0.01, family=PRIMARY_FAMILY))
    reg.register(_record("H1", "placebo:shuffled_signal_placebo", "ALL", "t1", 0.001, family=PLACEBO_FAMILY))
    result = apply_correction(reg, PRIMARY_FAMILY)
    assert result.n_registered == 1  # the placebo record must not be counted here
