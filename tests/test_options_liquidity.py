"""Phase 18, Part 22 — liquidity representation tests. Architecture only
-- no threshold is asserted as "the" liquidity cutoff (Part 14)."""

from __future__ import annotations

from datetime import datetime, timezone
from datetime import date as _date

from src.options.chain import OptionChainObservation
from src.options.instrument import OptionContract
from src.options.liquidity import compute_liquidity_metrics

CONTRACT = OptionContract(underlying_symbol="AAPL", option_id="dcec1c7b-45a3-40ce-b9e4-b02a82090d3c", call_put="call", strike=230.0, expiration=_date(2026, 9, 18))


def test_liquidity_metrics_from_real_live_quote():
    obs = OptionChainObservation.from_live_quote(
        CONTRACT, observation_timestamp=datetime(2026, 9, 2, 19, 59, 59, tzinfo=timezone.utc),
        bid=94.30, ask=97.15, last=95.725, volume=2, open_interest=1709,
    )
    lm = compute_liquidity_metrics(obs, as_of=datetime(2026, 9, 2, 20, 0, 0, tzinfo=timezone.utc))
    assert lm.bid_ask_spread is not None and abs(lm.bid_ask_spread - (97.15 - 94.30)) < 1e-9
    assert lm.spread_pct is not None
    assert lm.volume == 2
    assert lm.open_interest == 1709
    assert lm.quote_age_seconds == 1  # 20:00:00 - 19:59:59
    assert lm.has_tradeable_quote is True


def test_liquidity_metrics_from_historical_bar_has_no_spread():
    obs = OptionChainObservation.from_historical_bar(CONTRACT, observation_timestamp=datetime(2021, 12, 1, tzinfo=timezone.utc), close_price=3.53)
    lm = compute_liquidity_metrics(obs)
    assert lm.bid_ask_spread is None
    assert lm.spread_pct is None
    assert lm.has_tradeable_quote is False
    assert lm.volume is None
    assert lm.open_interest is None


def test_liquidity_metrics_quote_age_none_without_as_of():
    obs = OptionChainObservation.from_historical_bar(CONTRACT, observation_timestamp=datetime(2021, 12, 1, tzinfo=timezone.utc), close_price=3.53)
    lm = compute_liquidity_metrics(obs)
    assert lm.quote_age_seconds is None
