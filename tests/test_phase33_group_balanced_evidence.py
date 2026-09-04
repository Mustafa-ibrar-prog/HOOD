"""Phase 33, Part E/24 — DTE/moneyness/call-put-balanced pooled
relationships."""

from __future__ import annotations

import random

from src.options.phase33_group_balanced_evidence import group_balanced_pooled_relationship, group_relationships


def _rows(group_value: str, n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        x = rng.uniform(-1, 1)
        out.append({"feature": x, "target": x * 0.5 + rng.uniform(-0.1, 0.1), "group": group_value})
    return out


def test_group_relationships_one_result_per_real_group_value():
    rows = _rows("A", 20, 1) + _rows("B", 20, 2)
    results = group_relationships(rows, feature_col="feature", target_col="target", key_fn=lambda r: r["group"], group_label="test_group", min_observations=15)
    assert {r.group_value for r in results} == {"A", "B"}
    assert all(r.result is not None for r in results)


def test_group_below_min_observations_is_ineligible_not_dropped():
    rows = _rows("A", 5, 1)
    results = group_relationships(rows, feature_col="feature", target_col="target", key_fn=lambda r: r["group"], group_label="test_group", min_observations=15)
    assert len(results) == 1
    assert results[0].result is None
    assert "< min_observations" in results[0].reason


def test_no_group_invented_with_zero_real_observations():
    results = group_relationships([], feature_col="feature", target_col="target", key_fn=lambda r: r["group"], group_label="test_group")
    assert results == ()


def test_balanced_relationship_is_equal_weight_not_row_count_weighted():
    rows = _rows("A", 100, 1) + _rows("B", 15, 2)
    results = group_relationships(rows, feature_col="feature", target_col="target", key_fn=lambda r: r["group"], group_label="test_group", min_observations=15)
    balanced = group_balanced_pooled_relationship(results)
    assert balanced.n_groups_eligible == 2
    assert balanced.group_balanced_spearman is not None
    # equal-weight average must lie strictly between the two group correlations (never collapse to the dense group's own value)
    a_corr = next(r.result.spearman_correlation for r in results if r.group_value == "A")
    b_corr = next(r.result.spearman_correlation for r in results if r.group_value == "B")
    assert min(a_corr, b_corr) - 1e-9 <= balanced.group_balanced_spearman <= max(a_corr, b_corr) + 1e-9


def test_dominance_flagged_when_one_group_has_most_observations():
    rows = _rows("A", 200, 1) + _rows("B", 15, 2)
    results = group_relationships(rows, feature_col="feature", target_col="target", key_fn=lambda r: r["group"], group_label="test_group", min_observations=15)
    balanced = group_balanced_pooled_relationship(results, dominance_threshold=0.60)
    assert balanced.dominated_by_single_group is True
    assert balanced.dominant_group_value == "A"


def test_no_dominance_when_groups_are_balanced():
    rows = _rows("A", 20, 1) + _rows("B", 20, 2)
    results = group_relationships(rows, feature_col="feature", target_col="target", key_fn=lambda r: r["group"], group_label="test_group", min_observations=15)
    balanced = group_balanced_pooled_relationship(results, dominance_threshold=0.60)
    assert balanced.dominated_by_single_group is False
