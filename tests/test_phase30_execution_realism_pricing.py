"""Phase 30, Part 6/17 — execution realism price abstractions."""

from __future__ import annotations

import dataclasses

from src.options.execution_realism_pricing import (
    ExecutionPriceModel,
    buy_at_ask,
    buy_at_mid,
    delayed_execution,
    sell_at_bid,
    sell_at_mid,
    slippage_assumption,
)
from src.options.research_dataset import build_research_observations
from tests.phase30_fixtures import synthetic_multi_bar_store, synthetic_store


def test_buy_at_ask_uses_real_ask():
    store = synthetic_store()
    rows = build_research_observations(store)
    r = buy_at_ask(rows[0])
    assert r.model == ExecutionPriceModel.BUY_AT_ASK
    assert r.execution_price == rows[0].ask


def test_sell_at_bid_uses_real_bid():
    store = synthetic_store()
    rows = build_research_observations(store)
    r = sell_at_bid(rows[0])
    assert r.execution_price == rows[0].bid


def test_mid_price_models():
    store = synthetic_store()
    rows = build_research_observations(store)
    buy_mid = buy_at_mid(rows[0])
    sell_mid = sell_at_mid(rows[0])
    expected = (rows[0].bid + rows[0].ask) / 2
    assert buy_mid.execution_price == expected
    assert sell_mid.execution_price == expected


def test_missing_ask_is_execution_data_limited_never_fabricated():
    store = synthetic_store()
    rows = build_research_observations(store)
    poisoned = dataclasses.replace(rows[0], ask=None)
    r = buy_at_ask(poisoned)
    assert r.model == ExecutionPriceModel.EXECUTION_DATA_LIMITED
    assert r.execution_price is None


def test_never_uses_close_as_execution_price():
    store = synthetic_store()
    rows = build_research_observations(store)
    poisoned = dataclasses.replace(rows[0], ask=None, option_close=42.0)
    r = buy_at_ask(poisoned)
    assert r.execution_price is None  # NOT 42.0


def test_delayed_execution_finds_a_real_future_row():
    store = synthetic_multi_bar_store(n_bars=5)
    rows = build_research_observations(store)
    r = delayed_execution(rows[0], rows[1:], delay_count=2, base_model=ExecutionPriceModel.BUY_AT_ASK)
    assert r.model == ExecutionPriceModel.DELAYED_EXECUTION
    assert r.execution_price == rows[2].ask
    assert r.observation_timestamp == rows[2].observation_timestamp


def test_delayed_execution_data_limited_when_not_enough_future_rows():
    store = synthetic_multi_bar_store(n_bars=3)
    rows = build_research_observations(store)
    r = delayed_execution(rows[0], rows[1:], delay_count=10, base_model=ExecutionPriceModel.BUY_AT_ASK)
    assert r.model == ExecutionPriceModel.EXECUTION_DATA_LIMITED


def test_slippage_assumption_is_explicitly_labeled():
    store = synthetic_store()
    rows = build_research_observations(store)
    r = slippage_assumption(rows[0], side="buy", slippage_usd=0.02)
    assert r.model == ExecutionPriceModel.SLIPPAGE_ASSUMPTION
    assert r.slippage_assumption_usd == 0.02
    assert r.execution_price == rows[0].ask + 0.02


def test_slippage_assumption_sell_side_subtracts():
    store = synthetic_store()
    rows = build_research_observations(store)
    r = slippage_assumption(rows[0], side="sell", slippage_usd=0.02)
    assert r.execution_price == rows[0].bid - 0.02


def test_non_slippage_models_never_populate_slippage_field():
    store = synthetic_store()
    rows = build_research_observations(store)
    assert buy_at_ask(rows[0]).slippage_assumption_usd is None
    assert sell_at_bid(rows[0]).slippage_assumption_usd is None
    assert buy_at_mid(rows[0]).slippage_assumption_usd is None
