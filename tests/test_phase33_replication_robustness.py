"""Phase 33, Part G/24 — non-overlapping windows and real
expiration/year concentration."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from src.options.phase33_replication_robustness import (
    evaluate_non_overlap,
    expiration_concentration,
    non_overlapping_subsample,
    year_concentration,
)


def _bucket_series_rows(series_id: str, n: int, start: date) -> list[dict]:
    out = []
    for i in range(n):
        d = start + timedelta(days=i)
        out.append({
            "option_id": series_id, "timestamp": datetime(d.year, d.month, d.day),
            "feature": float(i % 5), "target": float((i % 5) * 0.3),
            "underlying_symbol": "AAPL", "call_put": "call", "moneyness_bucket": "near_atm",
            "cs_group_key": (d,),
        })
    return out


def test_non_overlapping_subsample_keeps_every_horizon_th_row_per_series():
    rows = _bucket_series_rows("S1", 12, date(2026, 1, 1))
    thinned = non_overlapping_subsample(rows, horizon=5)
    assert len(thinned) == 3  # indices 0, 5, 10
    dates = sorted(r["timestamp"] for r in thinned)
    assert dates[0] == datetime(2026, 1, 1)


def test_non_overlapping_subsample_never_invents_rows():
    rows = _bucket_series_rows("S1", 4, date(2026, 1, 1)) + _bucket_series_rows("S2", 3, date(2026, 2, 1))
    thinned = non_overlapping_subsample(rows, horizon=5)
    assert set(r["option_id"] for r in thinned) <= {"S1", "S2"}
    assert len(thinned) <= len(rows)


def test_evaluate_non_overlap_reduces_row_count():
    rows = _bucket_series_rows("S1", 30, date(2026, 1, 1))
    result = evaluate_non_overlap(rows, feature_col="feature", target_col="target", horizon=5)
    assert result.n_rows_after < result.n_rows_before
    assert result.n_rows_before == 30


def test_expiration_concentration_reports_real_shares():
    rows = [
        {"expiration": date(2023, 6, 16)}, {"expiration": date(2023, 6, 16)}, {"expiration": date(2022, 3, 18)},
    ]
    report = expiration_concentration(rows)
    assert report.n_rows == 3
    assert report.top_value == "2023-06-16"
    assert abs(report.top_share - 2 / 3) < 1e-9
    assert report.n_distinct == 2


def test_expiration_concentration_empty_input_never_fabricates():
    report = expiration_concentration([])
    assert report.n_rows == 0
    assert report.top_value is None
    assert report.top_share is None


def test_year_concentration_groups_by_real_timestamp_year():
    rows = [
        {"timestamp": datetime(2022, 1, 1)}, {"timestamp": datetime(2022, 6, 1)}, {"timestamp": datetime(2023, 1, 1)},
    ]
    report = year_concentration(rows)
    assert report.counts == {"2022": 2, "2023": 1}
    assert report.top_value == "2022"
