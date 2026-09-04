"""Phase 31, Parts 5 & 6/18 — CROSS_SECTIONAL and TIME_SERIES evidence."""

from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from src.options.expiration_diversity import CROSS_SECTIONAL_IC_UNDEFINED
from src.options.phase31_evidence import evaluate_cross_sectional_evidence, evaluate_time_series_evidence


def _cs_row(ts, underlying, expiration, option_id, feature, target):
    return {
        "timestamp": ts, "option_id": option_id, "underlying_symbol": underlying, "symbol": underlying,
        "cs_group_key": (underlying, expiration, ts), "feature": feature, "target": target,
    }


def test_cross_sectional_evidence_undefined_when_no_variance():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [_cs_row(ts, "AAPL", "2026-12-18", f"c{i}", 5.0, 0.01 * i) for i in range(5)]  # feature constant
    evidence = evaluate_cross_sectional_evidence(rows, feature_col="feature", target_col="target")
    assert evidence.applicable is False
    assert evidence.reason == CROSS_SECTIONAL_IC_UNDEFINED


def test_cross_sectional_evidence_computes_a_real_ic_with_enough_peers():
    rng = random.Random(1)
    rows = []
    for day in range(20):
        ts = datetime(2026, 1, 1 + day, tzinfo=timezone.utc)
        for i in range(6):
            feature = rng.uniform(-1, 1)
            target = 0.5 * feature + rng.gauss(0, 0.01)
            rows.append(_cs_row(ts, "AAPL", "2026-12-18", f"c{i}", feature, target))
    evidence = evaluate_cross_sectional_evidence(rows, feature_col="feature", target_col="target", min_universe_size=3)
    assert evidence.applicable is True
    assert evidence.report is not None
    assert evidence.report.ic_summary.average_ic is not None
    assert evidence.report.ic_summary.average_ic > 0.2  # strong real signal by construction


def test_cross_sectional_scoping_never_mixes_expirations():
    """Two peer groups with the SAME real timestamp but DIFFERENT
    expirations must never be pooled into one cross-sectional rank."""
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = (
        [_cs_row(ts, "AAPL", "2026-12-18", f"a{i}", i, i) for i in range(4)]
        + [_cs_row(ts, "AAPL", "2027-01-15", f"b{i}", -i, -i) for i in range(4)]  # opposite-signed group
    )
    evidence = evaluate_cross_sectional_evidence(rows, feature_col="feature", target_col="target", min_universe_size=3)
    # If expirations were wrongly pooled, the opposite-signed groups would partially cancel;
    # scoped correctly, each group individually has a perfect +1 IC.
    assert evidence.applicable is True
    assert evidence.report.ic_summary.average_ic == pytest.approx(1.0)


def test_time_series_evidence_flags_insufficient_contracts():
    rows = [{"option_id": "c1", "feature": 0.1, "target": 0.2}] * 3  # only 3 rows, well under min_obs
    evidence = evaluate_time_series_evidence(rows, feature_col="feature", target_col="target", horizon_bars=5)
    assert evidence.applicable is False
    assert evidence.n_contracts_eligible == 0


def test_time_series_evidence_computes_per_contract_correlation():
    rng = random.Random(2)
    rows = []
    for cid in range(6):
        for t in range(40):
            feature = rng.uniform(-1, 1)
            target = 0.6 * feature + rng.gauss(0, 0.05)
            rows.append({"option_id": f"c{cid}", "feature": feature, "target": target})
    evidence = evaluate_time_series_evidence(rows, feature_col="feature", target_col="target", horizon_bars=1, min_obs=10, min_independent_periods=5)
    assert evidence.applicable is True
    assert evidence.n_contracts_eligible == 6
    assert evidence.pooled_spearman_mean > 0.3
    assert evidence.sign_stable_fraction == 1.0


def test_time_series_independent_periods_scales_with_horizon():
    rows = [{"option_id": "c1", "feature": i * 0.01, "target": i * 0.02} for i in range(30)]
    evidence = evaluate_time_series_evidence(rows, feature_col="feature", target_col="target", horizon_bars=10, min_obs=10, min_independent_periods=2)
    result = evidence.per_contract[0]
    assert result.independent_periods_estimate == 30 // 10


def test_time_series_evidence_marks_constant_series_ineligible():
    rows = [{"option_id": "c1", "feature": 1.0, "target": 5.0}] * 30
    evidence = evaluate_time_series_evidence(rows, feature_col="feature", target_col="target", horizon_bars=1, min_obs=10, min_independent_periods=2)
    assert evidence.applicable is False
    assert evidence.per_contract[0].eligible is False
