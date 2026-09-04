"""Phase 30, Part 2/17 — the causal options feature engine."""

from __future__ import annotations

import dataclasses

from src.options.research_dataset import build_research_observations
from src.options.research_features import compute_features, compute_features_for_contract
from tests.phase30_fixtures import synthetic_multi_bar_store, synthetic_store


def test_basic_fields_present_and_finite():
    store = synthetic_store()
    rows = build_research_observations(store)
    feats = compute_features(rows)
    assert len(feats) == 2
    assert feats[0].moneyness == 100.0 / 190.0
    assert feats[0].is_call is True
    assert feats[0].time_to_expiration_years == feats[0].dte / 365.0


def test_first_row_has_no_momentum_or_return_not_enough_history():
    store = synthetic_multi_bar_store(n_bars=8)
    rows = build_research_observations(store)
    feats = compute_features(rows, lookback=5)
    assert feats[0].option_return is None
    assert feats[0].momentum is None


def test_momentum_and_return_computed_once_enough_history():
    store = synthetic_multi_bar_store(n_bars=8)
    rows = build_research_observations(store)
    feats = compute_features(rows, lookback=5)
    last = feats[-1]
    assert last.option_return is not None
    assert last.momentum is not None
    assert last.rolling_vol is not None
    # A steady real uptrend (option_close += 0.10/bar) -> positive momentum.
    assert last.momentum > 0


def test_underlying_trend_and_vol_regime_populated():
    store = synthetic_multi_bar_store(n_bars=8)
    rows = build_research_observations(store)
    feats = compute_features(rows, lookback=5)
    last = feats[-1]
    assert last.trend == "UP"
    assert last.vol_regime in ("LOW", "MEDIUM", "HIGH")
    assert last.underlying_momentum is not None and last.underlying_momentum > 0


def test_market_relative_return_always_none_no_benchmark_in_dataset():
    store = synthetic_multi_bar_store(n_bars=8)
    rows = build_research_observations(store)
    feats = compute_features(rows, lookback=5)
    assert all(f.market_relative_return is None for f in feats)


def test_liquidity_features():
    store = synthetic_multi_bar_store(n_bars=3)
    rows = build_research_observations(store)
    feats = compute_features(rows, lookback=5)
    for f in feats:
        assert f.quote_availability is True
        assert f.spread is not None and f.spread > 0
        assert f.spread_pct is not None
        assert f.volume is not None
        assert f.open_interest is not None
        assert f.volume_oi_ratio is not None


def test_reconstructed_iv_is_labeled_never_bare():
    store = synthetic_multi_bar_store(n_bars=3)
    rows = build_research_observations(store)
    feats = compute_features(rows, lookback=2)
    for f in feats:
        if f.reconstructed_iv is not None:
            assert f.iv_source == "RECONSTRUCTED_IV"
        else:
            assert f.iv_source is None


def test_iv_none_when_time_to_expiration_non_positive():
    from datetime import date
    store = synthetic_multi_bar_store(n_bars=1, expiration=date(2026, 8, 1))  # expires same day as the only bar
    rows = build_research_observations(store)
    feats = compute_features(rows)
    assert feats[0].reconstructed_iv is None
    assert feats[0].iv_source is None


def test_no_lookahead_synthetic_leakage_check():
    """The established leakage test pattern (src/features/base.py's own
    docstring, tests/test_feature_no_lookahead.py's real test): compute
    once normally, once with every row after a cutoff replaced by extreme
    values, and assert nothing at or before the cutoff changed."""
    store = synthetic_multi_bar_store(n_bars=8)
    rows = build_research_observations(store)
    baseline = compute_features_for_contract(rows, lookback=5)

    cutoff = 4
    poisoned_rows = list(rows[:cutoff])
    for r in rows[cutoff:]:
        poisoned_rows.append(dataclasses.replace(
            r, option_close=999999.0, option_high=999999.0, option_low=999999.0,
            bid=999999.0, ask=999999.0, volume=999999.0, open_interest=999999.0,
            underlying_price=999999.0,
        ))
    poisoned = compute_features_for_contract(poisoned_rows, lookback=5)

    for i in range(cutoff):
        assert baseline[i] == poisoned[i], f"row {i} changed when future data was poisoned"


def test_groups_by_contract_independently():
    """Two different contracts in the same call must never let one's
    history leak into the other's rolling computation."""
    store_a = synthetic_multi_bar_store(n_bars=5, strike=100.0)
    store_b = synthetic_multi_bar_store(n_bars=5, strike=105.0)
    combined_contracts = {**store_a.contracts, **store_b.contracts}
    combined_quotes = {**store_a.quotes, **store_b.quotes}
    combined_trades = {**store_a.trades, **store_b.trades}
    combined_oi = {**store_a.open_interest, **store_b.open_interest}
    from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
    combined = InMemoryLeanSampleStore(
        contracts=combined_contracts, lifecycles={**store_a.lifecycles, **store_b.lifecycles},
        quotes=combined_quotes, trades=combined_trades, open_interest=combined_oi,
        underlying=store_a.underlying,
    )
    rows = build_research_observations(combined)
    feats = compute_features(rows, lookback=5)
    option_ids = {f.option_id for f in feats}
    assert len(option_ids) == 2
    per_contract_first_rows = [f for f in feats if f.observation_timestamp == min(
        r.observation_timestamp for r in rows if r.option_id == f.option_id
    )]
    assert all(f.option_return is None for f in per_contract_first_rows)
