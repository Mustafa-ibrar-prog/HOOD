"""Tests for deterministic content-hash versioning — the mechanism behind
reproducible research."""

from __future__ import annotations

from src.data.versioning import compute_data_version, compute_feature_version, content_hash


def test_content_hash_is_deterministic():
    payload = {"a": 1, "b": "x"}
    assert content_hash(payload) == content_hash(payload)


def test_content_hash_is_key_order_independent():
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})


def test_content_hash_differs_on_different_content():
    assert content_hash({"a": 1}) != content_hash({"a": 2})


def test_compute_data_version_is_deterministic_for_same_inputs():
    kwargs = dict(source="hood", symbol="aapl", timeframe="day", start="2026-01-01", end="2026-06-01", record_count=100)
    assert compute_data_version(**kwargs) == compute_data_version(**kwargs)


def test_compute_data_version_normalizes_symbol_case():
    v1 = compute_data_version(source="hood", symbol="aapl", timeframe="day", start="a", end="b")
    v2 = compute_data_version(source="hood", symbol="AAPL", timeframe="day", start="a", end="b")
    assert v1 == v2


def test_compute_data_version_differs_on_different_range():
    v1 = compute_data_version(source="hood", symbol="AAPL", timeframe="day", start="2026-01-01", end="2026-06-01")
    v2 = compute_data_version(source="hood", symbol="AAPL", timeframe="day", start="2026-01-01", end="2026-07-01")
    assert v1 != v2


def test_compute_feature_version_is_order_independent():
    manifest_a = [
        {"name": "sma_20", "version": "1.0", "params": {"window": 20}},
        {"name": "momentum_10", "version": "1.0", "params": {"period": 10}},
    ]
    manifest_b = list(reversed(manifest_a))
    assert compute_feature_version(manifest_a) == compute_feature_version(manifest_b)


def test_compute_feature_version_differs_on_param_change():
    v1 = compute_feature_version([{"name": "sma_20", "version": "1.0", "params": {"window": 20}}])
    v2 = compute_feature_version([{"name": "sma_20", "version": "1.0", "params": {"window": 30}}])
    assert v1 != v2


def test_compute_feature_version_differs_on_version_bump():
    v1 = compute_feature_version([{"name": "sma_20", "version": "1.0", "params": {}}])
    v2 = compute_feature_version([{"name": "sma_20", "version": "2.0", "params": {}}])
    assert v1 != v2
