from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.polymarket.models import BinaryMarket
from src.polymarket.strategy import BtcMomentumStrategy, MomentumConfig


def _market(yes_bid: float, yes_ask: float) -> BinaryMarket:
    now = datetime.now(timezone.utc)
    return BinaryMarket(
        condition_id="c", question="Will BTC be up?", token_id_yes="y", token_id_no="n",
        close_time=now + timedelta(minutes=10), fetched_at=now, yes_bid=yes_bid, yes_ask=yes_ask,
    )


def test_no_candidate_with_too_few_samples():
    strategy = BtcMomentumStrategy()
    market = _market(0.58, 0.60)
    candidate = strategy.evaluate(market, recent_mids=[0.50, 0.55])  # below default min_samples=3
    assert candidate is None


def test_no_candidate_when_move_is_too_small():
    strategy = BtcMomentumStrategy()
    market = _market(0.51, 0.53)  # mid 0.52
    candidate = strategy.evaluate(market, recent_mids=[0.50, 0.505, 0.51])  # tiny drift
    assert candidate is None


def test_no_candidate_too_close_to_coinflip():
    strategy = BtcMomentumStrategy(MomentumConfig(min_move=0.01))  # loosen move threshold to isolate this check
    market = _market(0.49, 0.51)  # mid 0.50 exactly
    candidate = strategy.evaluate(market, recent_mids=[0.40, 0.45, 0.49])
    assert candidate is None


def test_rising_momentum_proposes_yes():
    strategy = BtcMomentumStrategy()
    market = _market(0.63, 0.65)  # mid 0.64
    candidate = strategy.evaluate(market, recent_mids=[0.50, 0.55, 0.60])
    assert candidate is not None
    assert candidate.thesis.outcome == "YES"
    assert candidate.suggested_entry_price == market.yes_ask


def test_falling_momentum_proposes_no():
    strategy = BtcMomentumStrategy()
    market = _market(0.35, 0.37)  # mid 0.36
    candidate = strategy.evaluate(market, recent_mids=[0.50, 0.45, 0.40])
    assert candidate is not None
    assert candidate.thesis.outcome == "NO"
    assert candidate.suggested_entry_price == round(1 - market.yes_bid, 4)


def test_size_scales_with_conviction_but_stays_bounded():
    config = MomentumConfig(min_size_usd=2.0, max_size_usd=5.0)
    strategy = BtcMomentumStrategy(config)
    small_move_market = _market(0.55, 0.57)
    small_candidate = strategy.evaluate(small_move_market, recent_mids=[0.50, 0.52, 0.54])
    big_move_market = _market(0.80, 0.82)
    big_candidate = strategy.evaluate(big_move_market, recent_mids=[0.50, 0.60, 0.70])
    assert small_candidate is not None and big_candidate is not None
    assert config.min_size_usd <= small_candidate.suggested_size_usd <= big_candidate.suggested_size_usd <= config.max_size_usd


def test_no_candidate_without_a_two_sided_quote_on_the_entry_side():
    strategy = BtcMomentumStrategy()
    market = _market(0.60, None)  # rising move but no ask to buy YES at
    candidate = strategy.evaluate(market, recent_mids=[0.50, 0.55, 0.58])
    assert candidate is None
