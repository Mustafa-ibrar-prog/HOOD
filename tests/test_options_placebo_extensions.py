"""Phase 21, Part 13 — placebo tests beyond Phase 7's
`src.research.cross_sectional_placebo` battery: within-symbol time
shuffle, symbol-identity shuffle, block-preserving shuffle, and the
sign-flip diagnostic (IC-based, for IC-metric candidates) plus their
GROUP-GAP mirrors (for group-mean-gap candidates like
P19-OPT-005-EXPANDED, whose primary metric is not an IC)."""

from __future__ import annotations

from datetime import date

from src.options.placebo_extensions import (
    block_preserving_shuffle_gap_placebo,
    block_preserving_shuffle_placebo,
    random_group_gap_control,
    shifted_group_gap_placebo,
    sign_flipped_target_diagnostic,
    sign_flipped_target_gap_diagnostic,
    shuffled_group_gap_placebo,
    symbol_identity_shuffle_gap_placebo,
    symbol_identity_shuffle_placebo,
    time_shuffled_target_gap_placebo,
    within_symbol_time_shuffle_gap_placebo,
    within_symbol_time_shuffle_placebo,
)


def _ic_row(symbol, ts, feature, target):
    return {"symbol": symbol, "underlying_symbol": symbol, "timestamp": ts, "feat": feature, "tgt": target}


def _ic_panel():
    rows = []
    for sym_i, sym in enumerate(("AAA", "BBB", "CCC")):
        for day in range(12):
            ts = date(2022, 1, 1 + day)
            feature = float(day + sym_i)
            target = feature * 0.1
            rows.append(_ic_row(sym, ts, feature, target))
    return rows


def _gap_row(underlying, ts, call_put, target):
    return {"underlying_symbol": underlying, "timestamp": ts, "call_put": call_put, "tgt": target}


def _gap_panel():
    # calls consistently earn more than puts, real signal built in on purpose
    rows = []
    for sym_i, sym in enumerate(("AAA", "BBB", "CCC")):
        for day in range(20):
            ts = date(2022, 1, 1 + day)
            rows.append(_gap_row(sym, ts, "call", 5.0 + sym_i))
            rows.append(_gap_row(sym, ts, "put", 1.0 + sym_i))
    return rows


# --- IC-based extension placebos ---


def test_within_symbol_time_shuffle_placebo_structural_fields():
    panel = _ic_panel()
    result = within_symbol_time_shuffle_placebo(panel, feature_col="feat", target_col="tgt", n_trials=50, seed=1, min_universe_size=2)
    assert result.method == "within_symbol_time_shuffle_placebo"
    assert result.observed_statistic is not None
    assert len(result.placebo_distribution) <= 50
    assert result.empirical_p_value is not None
    assert 0.0 <= result.empirical_p_value <= 1.0


def test_symbol_identity_shuffle_placebo_structural_fields():
    panel = _ic_panel()
    result = symbol_identity_shuffle_placebo(panel, feature_col="feat", target_col="tgt", n_trials=50, seed=2, min_universe_size=2)
    assert result.method == "symbol_identity_shuffle_placebo"
    assert result.observed_statistic is not None


def test_block_preserving_shuffle_placebo_structural_fields():
    panel = _ic_panel()
    result = block_preserving_shuffle_placebo(panel, feature_col="feat", target_col="tgt", block_size=3, n_trials=50, seed=3, min_universe_size=2)
    assert result.method == "block_preserving_shuffle_placebo(block_size=3)"
    assert result.observed_statistic is not None


def test_sign_flipped_target_diagnostic_is_exact_negation():
    panel = _ic_panel()
    result = sign_flipped_target_diagnostic(panel, feature_col="feat", target_col="tgt", min_universe_size=2)
    assert result.method == "sign_flipped_target_diagnostic"
    flipped = result.placebo_distribution[0]
    assert abs(flipped - (-result.observed_statistic)) < 1e-9


def test_ic_placebos_are_deterministic_given_seed():
    panel = _ic_panel()
    r1 = within_symbol_time_shuffle_placebo(panel, feature_col="feat", target_col="tgt", n_trials=30, seed=99, min_universe_size=2)
    r2 = within_symbol_time_shuffle_placebo(panel, feature_col="feat", target_col="tgt", n_trials=30, seed=99, min_universe_size=2)
    assert r1.placebo_distribution == r2.placebo_distribution


# --- GROUP-GAP mirror placebos ---


def test_shuffled_group_gap_placebo_observed_matches_real_gap():
    panel = _gap_panel()
    result = shuffled_group_gap_placebo(panel, target_col="tgt", n_trials=50, seed=1)
    assert result.method == "shuffled_group_gap_placebo"
    # real gap = mean(calls) - mean(puts); by construction calls are always 4.0 higher
    assert result.observed_statistic is not None
    assert abs(result.observed_statistic - 4.0) < 1e-9


def test_shuffled_group_gap_placebo_destroys_the_real_gap_on_average():
    panel = _gap_panel()
    result = shuffled_group_gap_placebo(panel, target_col="tgt", n_trials=200, seed=1)
    # shuffling call/put labels within each timestamp should center the placebo distribution near 0
    avg_placebo = sum(result.placebo_distribution) / len(result.placebo_distribution)
    assert abs(avg_placebo) < 1.0  # much smaller than the real gap of 4.0


def test_within_symbol_time_shuffle_gap_placebo_structural_fields():
    panel = _gap_panel()
    result = within_symbol_time_shuffle_gap_placebo(panel, target_col="tgt", n_trials=50, seed=2)
    assert result.method == "within_symbol_time_shuffle_gap_placebo"
    assert result.observed_statistic is not None
    assert abs(result.observed_statistic - 4.0) < 1e-9


def test_symbol_identity_shuffle_gap_placebo_structural_fields():
    panel = _gap_panel()
    result = symbol_identity_shuffle_gap_placebo(panel, target_col="tgt", n_trials=50, seed=3)
    assert result.method == "symbol_identity_shuffle_gap_placebo"
    assert result.observed_statistic is not None


def test_random_group_gap_control_returns_a_null_distribution():
    panel = _gap_panel()
    result = random_group_gap_control(panel, target_col="tgt", n_trials=100, seed=4)
    assert result.method == "random_group_gap_control"
    assert result.observed_statistic is None  # this IS the null distribution, not a comparison
    assert len(result.placebo_distribution) > 0
    avg_placebo = sum(result.placebo_distribution) / len(result.placebo_distribution)
    assert abs(avg_placebo) < 1.0  # a random group split should not reproduce the real gap of 4.0


def test_time_shuffled_target_gap_placebo_structural_fields():
    panel = _gap_panel()
    result = time_shuffled_target_gap_placebo(panel, target_col="tgt", n_trials=50, seed=5)
    assert result.method == "time_shuffled_target_gap_placebo"
    assert abs(result.observed_statistic - 4.0) < 1e-9


def test_block_preserving_shuffle_gap_placebo_structural_fields():
    panel = _gap_panel()
    result = block_preserving_shuffle_gap_placebo(panel, target_col="tgt", block_size=4, n_trials=50, seed=6)
    assert result.method == "block_preserving_shuffle_gap_placebo(block_size=4)"
    assert abs(result.observed_statistic - 4.0) < 1e-9


def test_sign_flipped_target_gap_diagnostic_is_exact_negation():
    panel = _gap_panel()
    result = sign_flipped_target_gap_diagnostic(panel, target_col="tgt")
    assert result.method == "sign_flipped_target_gap_diagnostic"
    flipped = result.placebo_distribution[0]
    assert abs(flipped - (-result.observed_statistic)) < 1e-9


def test_shifted_group_gap_placebo_is_deterministic_diagnostic():
    panel = _gap_panel()
    result = shifted_group_gap_placebo(panel, target_col="tgt", shift_bars=3)
    assert result.method == "shifted_group_gap_placebo(shift=3)"
    assert result.n_trials == 1
    assert result.empirical_p_value is None  # a diagnostic, not a distribution-based test


def test_gap_placebos_are_deterministic_given_seed():
    panel = _gap_panel()
    r1 = shuffled_group_gap_placebo(panel, target_col="tgt", n_trials=30, seed=77)
    r2 = shuffled_group_gap_placebo(panel, target_col="tgt", n_trials=30, seed=77)
    assert r1.placebo_distribution == r2.placebo_distribution


def test_gap_placebos_return_none_observed_when_one_group_missing():
    panel = [_gap_row("AAA", date(2022, 1, 1), "call", 5.0)]  # no puts at all
    result = shuffled_group_gap_placebo(panel, target_col="tgt", n_trials=10, seed=1)
    assert result.observed_statistic is None
