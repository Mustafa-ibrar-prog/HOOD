"""Phase 36, Part 6-8 — LiveMarketSnapshot, data provenance, and strict
timestamp semantics."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.market.models import EquityQuote, OptionQuote
from src.production.live_snapshot import OptionLiveState, build_live_market_snapshot
from src.production.provenance import (
    DataProvenance,
    HistoricalFeatureRequiredLiveError,
    ProvenancedFeature,
    assert_feature_acceptable_for_live_decision,
    assert_reconstructed_never_masquerades_as_live,
    unacceptable_features,
)
from src.production.timestamps import (
    DecisionTimestamps,
    LookaheadViolationError,
    StaleQuoteError,
    assert_no_lookahead,
    assert_quote_not_stale,
)


def _now():
    return datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc)


# --- LiveMarketSnapshot -----------------------------------------------------------------------


def test_build_live_market_snapshot_never_fabricates_missing_fields():
    equity = EquityQuote(symbol="AAPL", last_trade_price=230.0, previous_close=228.0, as_of=_now())
    option = OptionQuote(
        instrument_id="opt-1", bid_price=1.0, ask_price=1.1, last_trade_price=1.05,
        previous_close=0.9, volume=100, open_interest=200, as_of=_now(),
    )
    snap = build_live_market_snapshot(
        equity_quote=equity, option_quote=option, underlying_symbol="AAPL", option_id="opt-1",
        option_type="call", strike=230.0, expiration=date(2026, 10, 1), dte_days=26,
    )
    assert snap.option.bid == 1.0 and snap.option.ask == 1.1
    # Never fabricated -- these fields simply aren't on OptionQuote today.
    assert snap.option.bid_size is None
    assert snap.option.ask_size is None
    assert snap.option.implied_volatility is None
    assert snap.option.delta is None
    assert snap.underlying.bid is None  # EquityQuote carries no bid/ask


def test_build_live_market_snapshot_with_no_option_quote_still_carries_option_id():
    equity = EquityQuote(symbol="AAPL", last_trade_price=230.0, previous_close=228.0, as_of=_now())
    snap = build_live_market_snapshot(equity_quote=equity, underlying_symbol="AAPL", option_id="opt-1")
    assert snap.option is not None
    assert snap.option.option_id == "opt-1"
    assert snap.option.bid is None and snap.option.timestamp is None


def test_build_live_market_snapshot_with_no_option_at_all():
    equity = EquityQuote(symbol="AAPL", last_trade_price=230.0, previous_close=228.0, as_of=_now())
    snap = build_live_market_snapshot(equity_quote=equity, underlying_symbol="AAPL")
    assert snap.option is None


def test_option_live_state_rejects_invalid_option_type():
    with pytest.raises(ValueError):
        OptionLiveState(
            option_id="opt-1", underlying="AAPL", option_type="stock", strike=230.0, expiration=date(2026, 10, 1),
            dte_days=26, bid=1.0, ask=1.1, bid_size=None, ask_size=None, mark=1.05, volume=100, open_interest=200,
            implied_volatility=None, delta=None, gamma=None, theta=None, vega=None, rho=None, state="active",
            tradability="tradable", timestamp=_now(),
        )


# --- Provenance --------------------------------------------------------------------------------


def test_required_historical_feature_rejected_for_live_decision():
    feature = ProvenancedFeature("rsi14", 55.0, DataProvenance.HISTORICAL, required=True)
    with pytest.raises(HistoricalFeatureRequiredLiveError):
        assert_feature_acceptable_for_live_decision(feature)


def test_required_reconstructed_feature_rejected_for_live_decision():
    feature = ProvenancedFeature("rsi14_daily_reinterpretation", 55.0, DataProvenance.RECONSTRUCTED, required=True)
    with pytest.raises(HistoricalFeatureRequiredLiveError):
        assert_feature_acceptable_for_live_decision(feature)


def test_optional_historical_feature_accepted():
    feature = ProvenancedFeature("diagnostic_only", 55.0, DataProvenance.HISTORICAL, required=False)
    assert_feature_acceptable_for_live_decision(feature)  # must not raise


def test_live_and_derived_features_always_accepted():
    for provenance in (DataProvenance.LIVE, DataProvenance.DERIVED):
        assert_feature_acceptable_for_live_decision(ProvenancedFeature("x", 1.0, provenance, required=True))


def test_unacceptable_features_reports_all_violations():
    features = [
        ProvenancedFeature("a", 1.0, DataProvenance.LIVE, required=True),
        ProvenancedFeature("b", 2.0, DataProvenance.HISTORICAL, required=True),
        ProvenancedFeature("c", 3.0, DataProvenance.RECONSTRUCTED, required=True),
        ProvenancedFeature("d", 4.0, DataProvenance.HISTORICAL, required=False),
    ]
    bad = unacceptable_features(features)
    assert {f.name for f in bad} == {"b", "c"}


def test_reconstructed_feature_cannot_be_relabeled_live():
    feature = ProvenancedFeature("rsi14", 55.0, DataProvenance.RECONSTRUCTED, required=False)
    with pytest.raises(HistoricalFeatureRequiredLiveError):
        assert_reconstructed_never_masquerades_as_live(feature, claimed_provenance=DataProvenance.LIVE)
    assert_reconstructed_never_masquerades_as_live(feature, claimed_provenance=DataProvenance.RECONSTRUCTED)  # must not raise


# --- Timestamps ----------------------------------------------------------------------------


def test_decision_timestamps_enforce_ordering():
    t0 = _now()
    with pytest.raises(LookaheadViolationError):
        DecisionTimestamps(market_data_timestamp=t0 + timedelta(seconds=5), strategy_evaluation_timestamp=t0, decision_timestamp=t0)


def test_decision_timestamps_valid_ordering_succeeds():
    t0 = _now()
    dt = DecisionTimestamps(
        market_data_timestamp=t0, strategy_evaluation_timestamp=t0 + timedelta(seconds=1),
        decision_timestamp=t0 + timedelta(seconds=2),
    )
    assert dt.market_data_age_seconds(t0 + timedelta(seconds=10)) == 10.0


def test_assert_no_lookahead_raises_when_market_data_is_after_decision():
    t0 = _now()
    with pytest.raises(LookaheadViolationError):
        assert_no_lookahead(t0 + timedelta(seconds=1), t0)
    assert_no_lookahead(t0, t0)  # must not raise -- equal is fine


def test_stale_quote_detected():
    t0 = _now()
    with pytest.raises(StaleQuoteError):
        assert_quote_not_stale(t0 - timedelta(seconds=200), now=t0, max_age_seconds=90.0)
    assert_quote_not_stale(t0 - timedelta(seconds=10), now=t0, max_age_seconds=90.0)  # must not raise


def test_decision_timestamps_is_stale():
    t0 = _now()
    dt = DecisionTimestamps(market_data_timestamp=t0, strategy_evaluation_timestamp=t0, decision_timestamp=t0)
    assert dt.is_stale(t0 + timedelta(seconds=200), max_age_seconds=90.0)
    assert not dt.is_stale(t0 + timedelta(seconds=10), max_age_seconds=90.0)
