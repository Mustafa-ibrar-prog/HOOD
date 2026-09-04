"""Phase 33, Part C/24 — the coarse-grained range-expansion feature."""

from __future__ import annotations

from datetime import date, datetime

from src.options.phase32_bucket_definitions import FINE_SCHEME
from src.options.phase33_range_expansion_feature import (
    attach_range_expansion_features,
    build_range_expansion_bucket_table,
    compute_range_expansion_bucket_stats,
)


def _contract_row(underlying, call_put, dte_bucket, moneyness_bucket, d, range_expansion):
    return {
        "underlying_symbol": underlying, "call_put": call_put, "dte_bucket": dte_bucket,
        "moneyness_bucket": moneyness_bucket, "timestamp": datetime(d.year, d.month, d.day),
        "option_range_expansion": range_expansion,
    }


def test_median_mean_computed_from_real_values_only():
    key = ("AAPL", "call", "8-30", "near_atm", date(2026, 1, 5))
    rows = [
        _contract_row("AAPL", "call", "8-30", "near_atm", date(2026, 1, 5), 1.0),
        _contract_row("AAPL", "call", "8-30", "near_atm", date(2026, 1, 5), 2.0),
        _contract_row("AAPL", "call", "8-30", "near_atm", date(2026, 1, 5), None),  # excluded, never imputed
    ]
    stats = compute_range_expansion_bucket_stats(key, rows)
    assert stats.n_contracts_total == 3
    assert stats.n_contracts_with_value == 2
    assert stats.median_range_expansion == 1.5
    assert stats.mean_range_expansion == 1.5


def test_dispersion_none_below_two_values():
    key = ("AAPL", "call", "8-30", "near_atm", date(2026, 1, 5))
    rows = [_contract_row("AAPL", "call", "8-30", "near_atm", date(2026, 1, 5), 1.0)]
    stats = compute_range_expansion_bucket_stats(key, rows)
    assert stats.range_expansion_dispersion is None  # DATA_LIMITED, never fabricated


def test_log_mean_excludes_nonpositive_and_reports_the_exclusion():
    key = ("AAPL", "call", "8-30", "near_atm", date(2026, 1, 5))
    rows = [
        _contract_row("AAPL", "call", "8-30", "near_atm", date(2026, 1, 5), 1.0),
        _contract_row("AAPL", "call", "8-30", "near_atm", date(2026, 1, 5), 0.0),
    ]
    stats = compute_range_expansion_bucket_stats(key, rows)
    assert stats.log_mean_range_expansion is not None
    assert stats.n_excluded_nonpositive_for_log == 1


def test_no_bucket_with_zero_real_rows():
    table = build_range_expansion_bucket_table([], FINE_SCHEME)
    assert table == {}


def test_bucket_key_construction_matches_phase32_causal_grouping():
    """Same contract-day rows fed through Phase 32's own bucket-day
    builder and this module's builder must produce the SAME set of
    bucket keys -- no independent, potentially-inconsistent definition
    of bucket membership."""
    from src.options.phase32_bucket_panel import build_bucket_day_table

    rows = [
        _contract_row("AAPL", "call", "8-30", "near_atm", date(2026, 1, 5), 1.2),
        _contract_row("AAPL", "put", "8-30", "near_atm", date(2026, 1, 5), 0.8),
        _contract_row("GOOG", "call", "31-60", "otm", date(2026, 1, 6), 1.5),
    ]
    phase32_table = build_bucket_day_table(rows, FINE_SCHEME)
    range_expansion_table = build_range_expansion_bucket_table(rows, FINE_SCHEME)
    assert set(phase32_table.keys()) == set(range_expansion_table.keys())


def test_attach_merges_onto_bucket_rows_by_matching_key():
    contract_rows = [
        _contract_row("AAPL", "call", "8-30", "near_atm", date(2026, 1, 5), 1.2),
        _contract_row("AAPL", "call", "8-30", "near_atm", date(2026, 1, 5), 1.6),
    ]
    bucket_row = {
        "underlying_symbol": "AAPL", "call_put": "call", "dte_bucket": "8-30", "moneyness_bucket": "near_atm",
        "timestamp": datetime(2026, 1, 5),
    }
    merged = attach_range_expansion_features([bucket_row], contract_rows, FINE_SCHEME)
    assert len(merged) == 1
    assert merged[0]["bucket_range_expansion_median"] == 1.4
    assert merged[0]["bucket_range_expansion_n_with_value"] == 2


def test_attach_never_drops_a_bucket_row_missing_from_contract_panel():
    """A bucket-day row with NO matching range-expansion data gets None
    fields, never dropped and never fabricated."""
    bucket_row = {
        "underlying_symbol": "AAPL", "call_put": "call", "dte_bucket": "8-30", "moneyness_bucket": "near_atm",
        "timestamp": datetime(2026, 1, 5),
    }
    merged = attach_range_expansion_features([bucket_row], [], FINE_SCHEME)
    assert len(merged) == 1
    assert merged[0]["bucket_range_expansion_median"] is None
    assert merged[0]["bucket_range_expansion_n_with_value"] == 0
