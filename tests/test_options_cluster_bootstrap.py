"""Phase 23, Part 19 — the generic `cluster_bootstrap_ic`, which
generalizes `symbol_cluster_bootstrap_ic`'s resampling logic to an
arbitrary grouping key (expiration-cluster, year-cluster, ...)."""

from __future__ import annotations

from datetime import date

from src.options.dependence_bootstrap import (
    SymbolClusterBootstrapReport,
    cluster_bootstrap_ic,
    symbol_cluster_bootstrap_ic,
)


def _row(symbol, expiration, ts, feature, target):
    return {"underlying_symbol": symbol, "expiration": expiration, "timestamp": ts, "feat": feature, "tgt": target}


def _synthetic_panel():
    rows = []
    for sym_i, sym in enumerate(("AAA", "BBB", "CCC")):
        for exp_i, exp in enumerate(("2022-01-01", "2022-06-01")):
            for day in range(10):
                ts = date(2022, 1, 1 + day)
                feature = float(day + sym_i + exp_i)
                target = feature * 0.1 + (0.01 if day % 2 == 0 else -0.01)
                rows.append(_row(sym, exp, ts, feature, target))
    return rows


def test_cluster_bootstrap_ic_returns_report_type():
    panel = _synthetic_panel()
    report = cluster_bootstrap_ic(panel, feature_col="feat", target_col="tgt", cluster_key_fn=lambda r: r["expiration"], n_resamples=200, seed=1, min_universe_size=2)
    assert isinstance(report, SymbolClusterBootstrapReport)
    assert report.n_symbols == 2  # 2 distinct expirations


def test_cluster_bootstrap_ic_matches_symbol_cluster_bootstrap_when_keyed_by_symbol():
    """Using underlying_symbol as the cluster key should reproduce
    symbol_cluster_bootstrap_ic's point estimate and n_symbols exactly
    (same grouping, same underlying math)."""
    panel = _synthetic_panel()
    generic = cluster_bootstrap_ic(panel, feature_col="feat", target_col="tgt", cluster_key_fn=lambda r: r["underlying_symbol"], n_resamples=300, seed=42, min_universe_size=2)
    specific = symbol_cluster_bootstrap_ic(panel, feature_col="feat", target_col="tgt", n_resamples=300, seed=42, min_universe_size=2)
    assert generic.point_estimate == specific.point_estimate
    assert generic.n_symbols == specific.n_symbols
    assert generic.resampled_values == specific.resampled_values  # identical RNG usage -> identical resamples


def test_cluster_bootstrap_ic_by_year_uses_year_as_cluster_unit():
    rows = []
    for year in (2021, 2022, 2023):
        for day in range(10):
            ts = date(year, 1, 1 + day)
            for sym_i, sym in enumerate(("AAA", "BBB", "CCC")):
                feature = float(day + sym_i)
                target = feature * 0.1
                rows.append(_row(sym, "exp1", ts, feature, target))
    report = cluster_bootstrap_ic(rows, feature_col="feat", target_col="tgt", cluster_key_fn=lambda r: r["timestamp"].year, n_resamples=200, seed=5, min_universe_size=2)
    assert report.n_symbols == 3  # 3 distinct years


def test_cluster_bootstrap_ic_deterministic_given_seed():
    panel = _synthetic_panel()
    r1 = cluster_bootstrap_ic(panel, feature_col="feat", target_col="tgt", cluster_key_fn=lambda r: r["expiration"], n_resamples=150, seed=77, min_universe_size=2)
    r2 = cluster_bootstrap_ic(panel, feature_col="feat", target_col="tgt", cluster_key_fn=lambda r: r["expiration"], n_resamples=150, seed=77, min_universe_size=2)
    assert r1.resampled_values == r2.resampled_values


def test_cluster_bootstrap_ic_empty_panel_returns_none_bounds():
    report = cluster_bootstrap_ic([], feature_col="feat", target_col="tgt", cluster_key_fn=lambda r: r["expiration"], n_resamples=50, seed=1)
    assert report.n_symbols == 0
    assert report.point_estimate is None
    assert report.lower_bound is None
    assert report.upper_bound is None


def test_symbol_cluster_bootstrap_ic_still_behaves_exactly_as_before():
    """Regression guard: the original function's own signature/behavior
    must be completely unaffected by adding the generic variant."""
    panel = _synthetic_panel()
    report = symbol_cluster_bootstrap_ic(panel, feature_col="feat", target_col="tgt", n_resamples=100, seed=9, min_universe_size=2)
    assert report.n_symbols == 3  # 3 distinct underlying_symbol values
