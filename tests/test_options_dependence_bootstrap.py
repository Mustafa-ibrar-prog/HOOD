"""Phase 21, Part 15 — the symbol-cluster bootstrap (resamples whole
symbols with replacement, not individual rows)."""

from __future__ import annotations

from datetime import date

from src.options.dependence_bootstrap import SymbolClusterBootstrapReport, symbol_cluster_bootstrap_ic


def _row(symbol, ts, feature, target):
    return {"underlying_symbol": symbol, "symbol": f"{symbol}_{ts.isoformat()}", "timestamp": ts, "log_moneyness": feature, "forward_return_5": target}


def _synthetic_panel():
    # 3 symbols, each with a clean positive feature/target relationship plus noise across dates,
    # so a real point estimate and non-degenerate bootstrap distribution both exist.
    rows = []
    for sym_i, sym in enumerate(("AAA", "BBB", "CCC")):
        for day in range(10):
            ts = date(2022, 1, 1 + day)
            feature = float(day + sym_i)
            target = feature * 0.1 + (0.05 if day % 2 == 0 else -0.05)
            rows.append(_row(sym, ts, feature, target))
    return rows


def test_symbol_cluster_bootstrap_returns_report_type():
    panel = _synthetic_panel()
    report = symbol_cluster_bootstrap_ic(panel, feature_col="log_moneyness", target_col="forward_return_5", n_resamples=200, seed=1, min_universe_size=2)
    assert isinstance(report, SymbolClusterBootstrapReport)
    assert report.n_symbols == 3
    assert report.n_resamples == 200


def test_symbol_cluster_bootstrap_ci_brackets_point_estimate_roughly():
    panel = _synthetic_panel()
    report = symbol_cluster_bootstrap_ic(panel, feature_col="log_moneyness", target_col="forward_return_5", n_resamples=500, seed=2, min_universe_size=2)
    assert report.point_estimate is not None
    assert report.lower_bound is not None
    assert report.upper_bound is not None
    assert report.lower_bound <= report.upper_bound


def test_symbol_cluster_bootstrap_wider_ci_for_higher_confidence():
    panel = _synthetic_panel()
    report_90 = symbol_cluster_bootstrap_ic(panel, feature_col="log_moneyness", target_col="forward_return_5", n_resamples=500, seed=3, confidence_level=0.90, min_universe_size=2)
    report_95 = symbol_cluster_bootstrap_ic(panel, feature_col="log_moneyness", target_col="forward_return_5", n_resamples=500, seed=3, confidence_level=0.95, min_universe_size=2)
    width_90 = report_90.upper_bound - report_90.lower_bound
    width_95 = report_95.upper_bound - report_95.lower_bound
    assert width_95 >= width_90


def test_symbol_cluster_bootstrap_deterministic_given_seed():
    panel = _synthetic_panel()
    r1 = symbol_cluster_bootstrap_ic(panel, feature_col="log_moneyness", target_col="forward_return_5", n_resamples=200, seed=42, min_universe_size=2)
    r2 = symbol_cluster_bootstrap_ic(panel, feature_col="log_moneyness", target_col="forward_return_5", n_resamples=200, seed=42, min_universe_size=2)
    assert r1.resampled_values == r2.resampled_values
    assert r1.point_estimate == r2.point_estimate


def test_symbol_cluster_bootstrap_uses_symbol_count_not_row_count():
    """The resample draws exactly n_symbols choices (with replacement)
    from the SET of symbols -- not from the row count -- so a panel with
    few symbols but many rows per symbol still reflects symbol-level
    (not row-level) sample size."""
    panel = _synthetic_panel()  # 3 symbols x 10 rows = 30 rows
    report = symbol_cluster_bootstrap_ic(panel, feature_col="log_moneyness", target_col="forward_return_5", n_resamples=50, seed=7, min_universe_size=2)
    assert report.n_symbols == 3  # not 30


def test_symbol_cluster_bootstrap_empty_panel_returns_none_bounds():
    report = symbol_cluster_bootstrap_ic([], feature_col="log_moneyness", target_col="forward_return_5", n_resamples=50, seed=1)
    assert report.n_symbols == 0
    assert report.point_estimate is None
    assert report.lower_bound is None
    assert report.upper_bound is None
    assert report.resampled_values == ()


def test_symbol_cluster_bootstrap_render_contains_key_fields():
    panel = _synthetic_panel()
    report = symbol_cluster_bootstrap_ic(panel, feature_col="log_moneyness", target_col="forward_return_5", n_resamples=100, seed=9, min_universe_size=2)
    text = report.render()
    assert "Symbol-cluster bootstrap" in text
    assert "n_symbols=3" in text
