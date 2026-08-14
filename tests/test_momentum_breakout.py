from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.market.data_provider import MarketDataProvider
from src.market.errors import MarketDataError
from src.market.models import EquityQuote, MarketSnapshot, OptionQuote, UnderlyingSnapshot
from src.strategy.momentum_breakout import MomentumBreakoutConfig, MomentumBreakoutStrategy

TODAY = datetime.now(timezone.utc).date()


def _underlying_snapshot(**overrides) -> UnderlyingSnapshot:
    now = datetime.now(timezone.utc)
    defaults = dict(
        quote=EquityQuote(symbol="AAPL", last_trade_price=230.0, previous_close=225.0, as_of=now),
        bars=(),
        rsi=62.0,
        rsi_prev=58.0,
        macd_histogram=0.10,
        macd_histogram_prev=0.05,
        ema_fast=230.5,
        ema_slow=225.0,
        vwap=228.0,
        volume_ratio=1.4,
        higher_highs=True,
        lower_highs=False,
        breakout_continuation=True,
        failed_breakout=False,
        fetched_at=now,
    )
    defaults.update(overrides)
    return UnderlyingSnapshot(**defaults)


def _option_snapshot(bid=1.00, ask=1.05, volume=200, open_interest=500) -> MarketSnapshot:
    now = datetime.now(timezone.utc)
    return MarketSnapshot(
        option=OptionQuote(
            instrument_id="opt-1",
            bid_price=bid,
            ask_price=ask,
            last_trade_price=(bid + ask) / 2,
            previous_close=0.90,
            volume=volume,
            open_interest=open_interest,
            as_of=now,
        ),
        underlying=EquityQuote(symbol="AAPL", last_trade_price=230.0, previous_close=225.0, as_of=now),
        option_bars=(),
        underlying_bars=(),
        rsi=None,
        rsi_prev=None,
        macd_histogram=None,
        macd_histogram_prev=None,
        ema_fast=None,
        ema_slow=None,
        vwap=None,
        volume_ratio=None,
        fetched_at=now,
    )


class _FakeMarketDataProvider(MarketDataProvider):
    def __init__(self, *, underlying_snapshot=None, expirations=None, chain_candidates=None, option_snapshot=None, raise_on_underlying=False):
        self._underlying_snapshot = underlying_snapshot or _underlying_snapshot()
        self._expirations = expirations if expirations is not None else [TODAY + timedelta(days=14)]
        self._chain_candidates = chain_candidates if chain_candidates is not None else [{"id": "opt-1", "strike_price": "230.0000"}]
        self._option_snapshot = option_snapshot or _option_snapshot()
        self._raise_on_underlying = raise_on_underlying
        self.calls: list[str] = []

    def get_market_snapshot(self, option_id, underlying_symbol, now=None):
        self.calls.append("get_market_snapshot")
        return self._option_snapshot

    def get_underlying_snapshot(self, symbol, now=None):
        self.calls.append("get_underlying_snapshot")
        if self._raise_on_underlying:
            raise MarketDataError("simulated failure")
        return self._underlying_snapshot

    def get_option_expirations(self, underlying_symbol):
        self.calls.append("get_option_expirations")
        return self._expirations

    def get_option_chain_candidates(self, underlying_symbol, **filters):
        self.calls.append("get_option_chain_candidates")
        return self._chain_candidates


def test_produces_a_candidate_on_confirmed_strong_breakout():
    market = _FakeMarketDataProvider()
    strategy = MomentumBreakoutStrategy()
    candidates = strategy.scan(market, ["AAPL"])
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.underlying_symbol == "AAPL"
    assert candidate.side == "long_call"
    assert candidate.option_id == "opt-1"
    assert candidate.suggested_entry_price == 1.05  # the ask
    assert candidate.profit_target_usd == pytest.approx(1.05 * 100 * 0.50)
    assert candidate.stop_loss_usd == pytest.approx(1.05 * 100 * 0.50)


def test_no_candidate_without_breakout_continuation():
    market = _FakeMarketDataProvider(underlying_snapshot=_underlying_snapshot(breakout_continuation=False))
    strategy = MomentumBreakoutStrategy()
    assert strategy.scan(market, ["AAPL"]) == []


def test_no_candidate_when_momentum_is_only_stable_not_strengthening():
    weak = _underlying_snapshot(
        rsi=50.0,
        rsi_prev=None,
        macd_histogram=None,
        ema_fast=None,
        ema_slow=None,
        higher_highs=False,
        lower_highs=False,
        breakout_continuation=True,  # gate passes structurally...
        volume_ratio=1.0,
    )
    market = _FakeMarketDataProvider(underlying_snapshot=weak)
    strategy = MomentumBreakoutStrategy()
    assert strategy.scan(market, ["AAPL"]) == []


def test_no_candidate_when_no_expiration_in_dte_window():
    market = _FakeMarketDataProvider(expirations=[TODAY + timedelta(days=1)])  # too soon
    strategy = MomentumBreakoutStrategy(MomentumBreakoutConfig(min_days_to_expiration=7, max_days_to_expiration=45))
    assert strategy.scan(market, ["AAPL"]) == []


def test_selects_nearest_expiration_within_window():
    market = _FakeMarketDataProvider(
        expirations=[TODAY + timedelta(days=3), TODAY + timedelta(days=14), TODAY + timedelta(days=60)]
    )
    strategy = MomentumBreakoutStrategy(MomentumBreakoutConfig(min_days_to_expiration=7, max_days_to_expiration=45))
    candidates = strategy.scan(market, ["AAPL"])
    assert len(candidates) == 1
    assert candidates[0].expiration == TODAY + timedelta(days=14)


def test_selects_strike_nearest_the_money():
    market = _FakeMarketDataProvider(
        chain_candidates=[
            {"id": "opt-far", "strike_price": "300.0000"},
            {"id": "opt-near", "strike_price": "231.0000"},
            {"id": "opt-far2", "strike_price": "150.0000"},
        ]
    )
    strategy = MomentumBreakoutStrategy()
    candidates = strategy.scan(market, ["AAPL"])
    assert len(candidates) == 1
    assert candidates[0].option_id == "opt-near"


def test_no_candidate_when_no_chain_candidates_found():
    market = _FakeMarketDataProvider(chain_candidates=[])
    strategy = MomentumBreakoutStrategy()
    assert strategy.scan(market, ["AAPL"]) == []


def test_no_candidate_on_illiquid_contract():
    market = _FakeMarketDataProvider(option_snapshot=_option_snapshot(volume=1, open_interest=5))
    strategy = MomentumBreakoutStrategy(MomentumBreakoutConfig(min_volume=10, min_open_interest=50))
    assert strategy.scan(market, ["AAPL"]) == []


def test_no_candidate_on_wide_spread():
    market = _FakeMarketDataProvider(option_snapshot=_option_snapshot(bid=0.50, ask=1.50))
    strategy = MomentumBreakoutStrategy(MomentumBreakoutConfig(max_spread_pct=0.15))
    assert strategy.scan(market, ["AAPL"]) == []


def test_skips_symbol_on_market_data_error_and_continues_scanning():
    class _MixedProvider(_FakeMarketDataProvider):
        def get_underlying_snapshot(self, symbol, now=None):
            if symbol == "BROKEN":
                raise MarketDataError("no data")
            return super().get_underlying_snapshot(symbol, now)

    market = _MixedProvider()
    strategy = MomentumBreakoutStrategy()
    candidates = strategy.scan(market, ["BROKEN", "AAPL"])
    assert len(candidates) == 1
    assert candidates[0].underlying_symbol == "AAPL"


def test_scan_never_calls_order_placement_methods():
    market = _FakeMarketDataProvider()
    strategy = MomentumBreakoutStrategy()
    strategy.scan(market, ["AAPL"])
    order_related = {"place_option_order", "review_option_order", "cancel_option_order"}
    assert order_related.isdisjoint(set(market.calls))


def test_candidate_thesis_records_supporting_evidence():
    market = _FakeMarketDataProvider()
    strategy = MomentumBreakoutStrategy()
    candidate = strategy.scan(market, ["AAPL"])[0]
    assert candidate.thesis.direction == "bullish"
    assert candidate.thesis.setup_name == "momentum-breakout-calls"
    assert candidate.signals  # some evidence was recorded, not an empty tuple
