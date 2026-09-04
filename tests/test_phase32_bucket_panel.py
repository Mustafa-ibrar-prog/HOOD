"""Phase 32, Parts 3, 4 & 5/21 — causal bucket construction, features, targets."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.options.phase32_bucket_definitions import FINE_SCHEME
from src.options.phase32_bucket_panel import (
    attach_forward_targets,
    build_bucket_day_table,
    build_bucket_panel,
    build_feature_rows,
    compute_bucket_day_stats,
)

HORIZONS = (1, 3)


def _contract_row(
    underlying, ts, call_put, dte_bucket, moneyness_bucket, option_id, *,
    option_daily_return=None, option_high=None, option_low=None, option_close=None,
    bid=1.0, ask=1.1, volume=10.0, open_interest=100.0, spread_pct=0.05,
    underlying_price=100.0, underlying_daily_return=0.0, underlying_realized_vol=0.01,
    dte=20, moneyness_ratio=1.0, forward_underlying=None,
):
    row = {
        "underlying_symbol": underlying, "timestamp": ts, "call_put": call_put, "dte_bucket": dte_bucket,
        "moneyness_bucket": moneyness_bucket, "option_id": option_id, "expiration": "2026-12-18",
        "dte": dte, "moneyness_ratio": moneyness_ratio,
        "option_daily_return": option_daily_return, "option_high": option_high, "option_low": option_low, "option_close": option_close,
        "bid": bid, "ask": ask, "volume": volume, "open_interest": open_interest, "spread_pct": spread_pct,
        "underlying_price": underlying_price, "underlying_daily_return": underlying_daily_return,
        "underlying_realized_vol": underlying_realized_vol, "data_quality": "clean",
    }
    for h in HORIZONS:
        row[f"forward_underlying_return_{h}"] = forward_underlying
    return row


def test_compute_bucket_day_stats_basic():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    key = ("AAPL", "call", "8-30", "near_atm", date(2026, 1, 1))
    rows = [
        _contract_row("AAPL", ts, "call", "8-30", "near_atm", "c1", option_daily_return=0.10),
        _contract_row("AAPL", ts, "call", "8-30", "near_atm", "c2", option_daily_return=-0.05),
        _contract_row("AAPL", ts, "call", "8-30", "near_atm", "c3", option_daily_return=0.02),
    ]
    stats = compute_bucket_day_stats(key, rows, horizons=HORIZONS)
    assert stats.n_contracts == 3
    assert stats.n_valid_returns == 3
    assert stats.median_return == 0.02
    assert stats.positive_return_fraction == 2 / 3


def test_bucket_table_groups_by_full_key():
    ts1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ts2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    rows = [
        _contract_row("AAPL", ts1, "call", "8-30", "near_atm", "c1", option_daily_return=0.1),
        _contract_row("AAPL", ts2, "call", "8-30", "near_atm", "c1", option_daily_return=0.2),
        _contract_row("AAPL", ts1, "put", "8-30", "near_atm", "c2", option_daily_return=-0.1),
    ]
    table = build_bucket_day_table(rows, FINE_SCHEME, horizons=HORIZONS)
    assert len(table) == 3  # (call,ts1), (call,ts2), (put,ts1)


def test_bucket_excludes_rows_without_a_valid_bucket_classification():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [_contract_row("AAPL", ts, "call", None, "near_atm", "c1", option_daily_return=0.1)]
    table = build_bucket_day_table(rows, FINE_SCHEME, horizons=HORIZONS)
    assert table == {}


def test_call_put_spread_computed_from_sibling_bucket():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        _contract_row("AAPL", ts, "call", "8-30", "near_atm", "c1", option_daily_return=0.10),
        _contract_row("AAPL", ts, "put", "8-30", "near_atm", "p1", option_daily_return=-0.04),
    ]
    table = build_bucket_day_table(rows, FINE_SCHEME, horizons=HORIZONS)
    feature_rows = build_feature_rows(table, FINE_SCHEME)
    call_row = next(r for r in feature_rows if r["call_put"] == "call")
    assert call_row["call_put_return_spread"] == 0.10 - (-0.04)


def test_moneyness_spread_computed_across_sibling_buckets():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        _contract_row("AAPL", ts, "call", "8-30", "near_atm", "atm1", option_daily_return=0.0),
        _contract_row("AAPL", ts, "call", "8-30", "otm", "otm1", option_daily_return=0.30),
        _contract_row("AAPL", ts, "call", "8-30", "itm", "itm1", option_daily_return=-0.02),
    ]
    table = build_bucket_day_table(rows, FINE_SCHEME, horizons=HORIZONS)
    feature_rows = build_feature_rows(table, FINE_SCHEME)
    atm_row = next(r for r in feature_rows if r["moneyness_bucket"] == "near_atm")
    assert atm_row["otm_atm_spread"] == 0.30 - 0.0
    assert atm_row["itm_atm_spread"] == -0.02 - 0.0


def test_dte_spread_computed_across_sibling_buckets():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        _contract_row("AAPL", ts, "call", "0-7", "near_atm", "s1", option_daily_return=0.0),
        _contract_row("AAPL", ts, "call", "31-60", "near_atm", "m1", option_daily_return=0.05),
        _contract_row("AAPL", ts, "call", "120+", "near_atm", "l1", option_daily_return=0.10),
    ]
    table = build_bucket_day_table(rows, FINE_SCHEME, horizons=HORIZONS)
    feature_rows = build_feature_rows(table, FINE_SCHEME)
    short_row = next(r for r in feature_rows if r["dte_bucket"] == "0-7")
    assert short_row["short_medium_dte_spread"] == 0.05 - 0.0


def test_option_vs_underlying_features():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [_contract_row("AAPL", ts, "call", "8-30", "near_atm", "c1", option_daily_return=0.05, underlying_daily_return=0.01)]
    table = build_bucket_day_table(rows, FINE_SCHEME, horizons=HORIZONS)
    feature_rows = build_feature_rows(table, FINE_SCHEME)
    row = feature_rows[0]
    assert abs(row["option_minus_underlying_return"] - 0.04) < 1e-9
    assert abs(row["option_magnitude_minus_underlying_magnitude"] - (0.05 - 0.01)) < 1e-9


def test_no_delta_scaled_feature_is_ever_fabricated():
    """Part 4E: only use delta if genuinely available -- this dataset has
    none, so no row should ever carry a 'delta_scaled' key."""
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [_contract_row("AAPL", ts, "call", "8-30", "near_atm", "c1", option_daily_return=0.05)]
    table = build_bucket_day_table(rows, FINE_SCHEME, horizons=HORIZONS)
    feature_rows = build_feature_rows(table, FINE_SCHEME)
    assert all("delta" not in k for k in feature_rows[0])


def test_forward_targets_compound_across_real_bucket_dates():
    ts_base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    returns = [0.10, 0.10, 0.10, 0.10]  # 4 consecutive real bucket-dates
    for i, ret in enumerate(returns):
        ts = datetime(2026, 1, 1 + i, tzinfo=timezone.utc)
        rows.append(_contract_row("AAPL", ts, "call", "8-30", "near_atm", f"c{i}", option_daily_return=ret))
    table = build_bucket_day_table(rows, FINE_SCHEME, horizons=(1, 3))
    feature_rows = build_feature_rows(table, FINE_SCHEME)
    targeted = attach_forward_targets(feature_rows, horizons=(1, 3))
    first = min(targeted, key=lambda r: r["timestamp"])
    assert abs(first["forward_bucket_return_1"] - 0.10) < 1e-9
    expected_3 = (1.10 ** 3) - 1
    assert abs(first["forward_bucket_return_3"] - expected_3) < 1e-9


def test_forward_targets_none_when_insufficient_future_dates():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [_contract_row("AAPL", ts, "call", "8-30", "near_atm", "c1", option_daily_return=0.1)]
    table = build_bucket_day_table(rows, FINE_SCHEME, horizons=(1,))
    feature_rows = build_feature_rows(table, FINE_SCHEME)
    targeted = attach_forward_targets(feature_rows, horizons=(1,))
    assert targeted[0]["forward_bucket_return_1"] is None
    assert targeted[0]["forward_bucket_mfe_1"] is None


def test_no_survivorship_leakage_bucket_membership_independent_of_future():
    """A bucket's membership/stats at date t must be identical whether or
    not a LATER date's data exists at all."""
    ts1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ts2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    row_t1 = _contract_row("AAPL", ts1, "call", "8-30", "near_atm", "c1", option_daily_return=0.05)

    table_without_future = build_bucket_day_table([row_t1], FINE_SCHEME, horizons=(1,))
    table_with_future = build_bucket_day_table(
        [row_t1, _contract_row("AAPL", ts2, "call", "8-30", "near_atm", "c1", option_daily_return=0.20)],
        FINE_SCHEME, horizons=(1,),
    )
    key = ("AAPL", "call", "8-30", "near_atm", date(2026, 1, 1))
    assert table_without_future[key].median_return == table_with_future[key].median_return
    assert table_without_future[key].n_contracts == table_with_future[key].n_contracts


def test_build_bucket_panel_end_to_end_smoke():
    rows = []
    for i in range(6):
        ts = datetime(2026, 1, 1 + i, tzinfo=timezone.utc)
        for cid, ret in (("c1", 0.05), ("c2", -0.02), ("c3", 0.01)):
            rows.append(_contract_row("AAPL", ts, "call", "8-30", "near_atm", cid, option_daily_return=ret))
    panel = build_bucket_panel(rows, FINE_SCHEME, horizons=(1, 3))
    assert len(panel) == 6
    assert all("forward_bucket_return_1" in r for r in panel)
    assert all("cs_group_key" in r for r in panel)
