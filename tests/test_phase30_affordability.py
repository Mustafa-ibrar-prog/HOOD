"""Phase 30, Part 5/17 — affordability calculations for a ~$1,000 account."""

from __future__ import annotations

import dataclasses

from src.options.affordability import analyze_affordability, analyze_affordability_batch
from src.options.research_dataset import build_research_observations
from tests.phase30_fixtures import synthetic_multi_bar_store, synthetic_store


def test_affordability_computed_from_real_ask():
    store = synthetic_store()
    rows = build_research_observations(store)
    a = analyze_affordability(rows[0], account_equity_usd=1000.0)
    assert a.premium_cost_usd == 5.00 * 100
    assert a.data_limited is False
    assert a.contracts_affordable == 1000 // 500
    assert a.max_capital_required_usd == a.contracts_affordable * a.premium_cost_usd
    assert 0 <= a.capital_pct <= 1.0


def test_no_ask_yields_all_none_and_data_limited():
    store = synthetic_store()
    rows = build_research_observations(store)
    poisoned = dataclasses.replace(rows[0], ask=None)
    a = analyze_affordability(poisoned)
    assert a.data_limited is True
    assert a.premium_cost_usd is None
    assert a.contracts_affordable is None
    assert a.max_capital_required_usd is None
    assert a.spread_cost_usd is None


def test_no_bid_still_computes_premium_but_not_spread_cost():
    store = synthetic_store()
    rows = build_research_observations(store)
    poisoned = dataclasses.replace(rows[0], bid=None)
    a = analyze_affordability(poisoned)
    assert a.data_limited is True
    assert a.premium_cost_usd is not None
    assert a.contracts_affordable is not None
    assert a.spread_cost_usd is None


def test_tick_impact_scales_with_position_size():
    store = synthetic_multi_bar_store(n_bars=1)
    rows = build_research_observations(store)
    a = analyze_affordability(rows[0], account_equity_usd=100000.0, tick_size_usd=0.01)
    assert a.tick_impact_usd == 0.01 * 100 * a.contracts_affordable


def test_spread_cost_reflects_full_position():
    store = synthetic_store()
    rows = build_research_observations(store)
    a = analyze_affordability(rows[0])
    expected_spread = (rows[0].ask - rows[0].bid) * 100 * a.contracts_affordable
    assert a.spread_cost_usd == expected_spread


def test_zero_equity_never_divides_by_zero():
    store = synthetic_store()
    rows = build_research_observations(store)
    a = analyze_affordability(rows[0], account_equity_usd=0.0)
    assert a.contracts_affordable == 0
    assert a.max_capital_required_usd == 0.0


def test_batch_matches_row_count():
    store = synthetic_multi_bar_store(n_bars=6)
    rows = build_research_observations(store)
    results = analyze_affordability_batch(rows)
    assert len(results) == len(rows)


def test_never_uses_close_as_execution_price():
    """Regression guard: even if option_close differs wildly from ask,
    premium_cost_usd must track ask, never close."""
    store = synthetic_store()
    rows = build_research_observations(store)
    poisoned = dataclasses.replace(rows[0], option_close=99999.0)
    a = analyze_affordability(poisoned)
    assert a.premium_cost_usd == rows[0].ask * 100
