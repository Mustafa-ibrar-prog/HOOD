from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.polymarket.models import BinaryMarket, BookLevel, OrderBookSnapshot
from src.polymarket.risk import PolymarketRiskManager
from src.polymarket.settings import PolymarketSettings
from src.polymarket.state import DailyPnlState


def _settings(**overrides) -> PolymarketSettings:
    env = {
        "POLYMARKET_MAX_BET_USD": "5.0", "POLYMARKET_MAX_DAILY_LOSS_USD": "20.0",
        "POLYMARKET_MAX_OPEN_POSITIONS": "1", "POLYMARKET_COOLDOWN_SECONDS_AFTER_EXIT": "60",
        "POLYMARKET_STALE_DATA_MAX_SECONDS": "20.0", "POLYMARKET_MAX_SPREAD_PCT": "0.05",
        "POLYMARKET_ENTRY_CUTOFF_SECONDS_BEFORE_CLOSE": "120",
        "POLYMARKET_MIN_ORDER_BOOK_LIQUIDITY_USD": "25.0",
    }
    env.update(overrides)
    return PolymarketSettings.from_env(env=env)


def _market(**overrides) -> BinaryMarket:
    now = datetime.now(timezone.utc)
    defaults = dict(
        condition_id="c", question="q", token_id_yes="y", token_id_no="n",
        close_time=now + timedelta(minutes=10), fetched_at=now, yes_bid=0.48, yes_ask=0.50,
    )
    defaults.update(overrides)
    return BinaryMarket(**defaults)


def _state(**overrides) -> DailyPnlState:
    defaults = dict(trade_date=datetime.now(timezone.utc).date())
    defaults.update(overrides)
    return DailyPnlState(**defaults)


def _book(**overrides) -> OrderBookSnapshot:
    # $50 of executable liquidity at 0.50 by default — comfortably above
    # the $25 default threshold used by _settings() above.
    defaults = dict(
        token_id="y", bids=(BookLevel(price=0.48, size=100.0),), asks=(BookLevel(price=0.50, size=100.0),),
        fetched_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return OrderBookSnapshot(**defaults)


def _evaluate(risk, **overrides):
    kwargs = dict(size_usd=5.0, market=_market(), state=_state(), order_book=_book(), side="BUY", max_price=0.55)
    kwargs.update(overrides)
    return risk.evaluate_new_trade(**kwargs)


def test_all_checks_pass_for_a_clean_trade():
    risk = PolymarketRiskManager(_settings())
    decision = _evaluate(risk)
    assert decision.allowed
    assert decision.reasons_failed == ()


def test_bet_size_over_limit_blocks():
    risk = PolymarketRiskManager(_settings())
    decision = _evaluate(risk, size_usd=100.0)
    assert not decision.allowed
    assert any("exceeds limit" in r for r in decision.reasons_failed)


def test_daily_loss_limit_blocks_new_entries():
    risk = PolymarketRiskManager(_settings())
    decision = _evaluate(risk, state=_state(realized_pnl_usd=-25.0))
    assert not decision.allowed
    assert any("loss limit" in r.lower() for r in decision.reasons_failed)


def test_max_open_positions_blocks():
    risk = PolymarketRiskManager(_settings())
    decision = _evaluate(risk, state=_state(open_position_count=1))
    assert not decision.allowed


def test_cooldown_blocks_right_after_an_exit():
    risk = PolymarketRiskManager(_settings())
    now = datetime.now(timezone.utc)
    state = _state(last_exit_time=(now - timedelta(seconds=5)).isoformat())
    decision = _evaluate(risk, state=state, now=now)
    assert not decision.allowed
    assert any("cooldown" in r.lower() for r in decision.reasons_failed)


def test_cooldown_clears_after_enough_time():
    risk = PolymarketRiskManager(_settings())
    now = datetime.now(timezone.utc)
    state = _state(last_exit_time=(now - timedelta(seconds=120)).isoformat())
    decision = _evaluate(risk, state=state, now=now)
    assert decision.allowed


def test_stale_data_blocks():
    risk = PolymarketRiskManager(_settings())
    stale_market = _market(fetched_at=datetime.now(timezone.utc) - timedelta(seconds=60))
    decision = _evaluate(risk, market=stale_market)
    assert not decision.allowed
    assert any("stale" in r.lower() for r in decision.reasons_failed)


def test_wide_spread_blocks():
    risk = PolymarketRiskManager(_settings())
    wide_market = _market(yes_bid=0.30, yes_ask=0.70)
    decision = _evaluate(risk, market=wide_market)
    assert not decision.allowed
    assert any("spread" in r.lower() for r in decision.reasons_failed)


def test_entry_cutoff_blocks_near_close():
    risk = PolymarketRiskManager(_settings())
    closing_soon = _market(close_time=datetime.now(timezone.utc) + timedelta(seconds=30))
    decision = _evaluate(risk, market=closing_soon)
    assert not decision.allowed
    assert any("cutoff" in r.lower() for r in decision.reasons_failed)


def test_missing_quote_blocks_spread_check():
    risk = PolymarketRiskManager(_settings())
    no_quote = _market(yes_bid=None, yes_ask=None)
    decision = _evaluate(risk, market=no_quote)
    assert not decision.allowed


def test_multiple_failures_all_reported_together():
    risk = PolymarketRiskManager(_settings())
    bad_market = _market(yes_bid=0.30, yes_ask=0.70, close_time=datetime.now(timezone.utc) + timedelta(seconds=10))
    decision = _evaluate(risk, size_usd=100.0, market=bad_market, state=_state(realized_pnl_usd=-25.0))
    assert not decision.allowed
    assert len(decision.reasons_failed) >= 3


# --- Order-book liquidity (Task 6) --------------------------------------------
# check_order_book_liquidity() must evaluate the SPECIFIC side/outcome being
# bought against its OWN order book — never an unrelated aggregate.

def test_liquidity_sufficient_allows_trade():
    risk = PolymarketRiskManager(_settings(POLYMARKET_MIN_ORDER_BOOK_LIQUIDITY_USD="25.0"))
    book = _book(asks=(BookLevel(price=0.50, size=100.0),))  # $50 >= $25
    decision = _evaluate(risk, order_book=book, max_price=0.55)
    assert decision.allowed


def test_liquidity_insufficient_blocks_trade():
    risk = PolymarketRiskManager(_settings(POLYMARKET_MIN_ORDER_BOOK_LIQUIDITY_USD="25.0"))
    book = _book(asks=(BookLevel(price=0.50, size=10.0),))  # only $5
    decision = _evaluate(risk, order_book=book, max_price=0.55)
    assert not decision.allowed
    assert any("liquidity" in r.lower() for r in decision.reasons_failed)


def test_liquidity_empty_book_blocks_trade():
    risk = PolymarketRiskManager(_settings(POLYMARKET_MIN_ORDER_BOOK_LIQUIDITY_USD="25.0"))
    book = _book(asks=())
    decision = _evaluate(risk, order_book=book, max_price=0.99)
    assert not decision.allowed
    assert any("liquidity" in r.lower() for r in decision.reasons_failed)


def test_liquidity_malformed_zero_size_level_blocks_trade():
    risk = PolymarketRiskManager(_settings(POLYMARKET_MIN_ORDER_BOOK_LIQUIDITY_USD="25.0"))
    book = _book(asks=(BookLevel(price=0.50, size=0.0),))
    decision = _evaluate(risk, order_book=book, max_price=0.99)
    assert not decision.allowed


def test_liquidity_one_sided_book_blocks_a_buy_with_no_asks():
    risk = PolymarketRiskManager(_settings(POLYMARKET_MIN_ORDER_BOOK_LIQUIDITY_USD="25.0"))
    book = _book(bids=(BookLevel(price=0.48, size=1000.0),), asks=())
    decision = _evaluate(risk, order_book=book, side="BUY", max_price=0.99)
    assert not decision.allowed


def test_liquidity_exactly_at_threshold_passes():
    risk = PolymarketRiskManager(_settings(POLYMARKET_MIN_ORDER_BOOK_LIQUIDITY_USD="25.0"))
    book = _book(asks=(BookLevel(price=0.50, size=50.0),))  # exactly $25.00
    decision = _evaluate(risk, order_book=book, max_price=0.55)
    liquidity_result = next(r for r in decision.results if r.name == "ORDER_BOOK_LIQUIDITY")
    assert liquidity_result.passed


def test_liquidity_check_ignores_levels_above_max_price():
    risk = PolymarketRiskManager(_settings(POLYMARKET_MIN_ORDER_BOOK_LIQUIDITY_USD="25.0"))
    # $50 of liquidity exists, but only at a price above our ceiling.
    book = _book(asks=(BookLevel(price=0.90, size=100.0),))
    decision = _evaluate(risk, order_book=book, max_price=0.55)
    assert not decision.allowed
