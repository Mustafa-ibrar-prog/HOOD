"""Phase 37, Part 9/17/18 — provenance vocabulary, DTE, and moneyness."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.research_recorder.dte import compute_dte
from src.research_recorder.moneyness import compute_moneyness
from src.research_recorder.provenance import LiveObservationProvenance


def test_provenance_has_exactly_three_values():
    assert {p.value for p in LiveObservationProvenance} == {"LIVE", "DERIVED_FROM_LIVE", "MISSING"}


def test_provenance_never_includes_historical_or_reconstructed():
    names = {p.name for p in LiveObservationProvenance}
    assert "HISTORICAL" not in names
    assert "RECONSTRUCTED" not in names


def test_dte_positive_for_future_expiration():
    # 15:00 UTC = 11:00 ET in September (daylight saving) -- safely mid-day
    # local, avoiding the midnight-UTC/date-boundary edge case a naive test
    # would otherwise trip over (see the timezone-conversion test below).
    now = datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc)
    assert compute_dte(expiration=date(2026, 10, 5), observation_timestamp=now, market_timezone="America/New_York") == 30


def test_dte_negative_for_past_expiration():
    now = datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc)
    assert compute_dte(expiration=date(2026, 8, 5), observation_timestamp=now, market_timezone="America/New_York") < 0


def test_dte_respects_timezone_conversion_across_a_date_boundary():
    """Midnight UTC on 2026-09-05 is still 2026-09-04 evening in US
    Eastern time (UTC-4 under daylight saving) -- DTE must be computed
    against the LOCAL date, not the raw UTC date, or this would silently
    be off by one near midnight UTC (Part 18's explicit timezone
    documentation)."""
    midnight_utc = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)
    assert compute_dte(expiration=date(2026, 10, 5), observation_timestamp=midnight_utc, market_timezone="America/New_York") == 31


def test_dte_zero_on_expiration_day():
    now = datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc)
    assert compute_dte(expiration=date(2026, 9, 5), observation_timestamp=now, market_timezone="America/New_York") == 0


def test_dte_naive_datetime_treated_as_already_local():
    now = datetime(2026, 9, 5, 10, 0)  # naive
    assert compute_dte(expiration=date(2026, 9, 15), observation_timestamp=now, market_timezone="America/New_York") == 10


def test_moneyness_call_itm_when_underlying_above_strike():
    result = compute_moneyness(underlying_price=110.0, strike=100.0, option_type="call")
    assert result.moneyness > 0


def test_moneyness_put_itm_when_underlying_below_strike():
    result = compute_moneyness(underlying_price=90.0, strike=100.0, option_type="put")
    assert result.moneyness > 0


def test_moneyness_none_when_strike_missing():
    result = compute_moneyness(underlying_price=100.0, strike=None, option_type="call")
    assert result.moneyness is None


def test_moneyness_none_when_underlying_price_missing():
    result = compute_moneyness(underlying_price=None, strike=100.0, option_type="call")
    assert result.moneyness is None


def test_moneyness_stores_the_exact_price_used_and_a_version():
    result = compute_moneyness(underlying_price=100.0, strike=95.0, option_type="call")
    assert result.underlying_price_used == 100.0
    assert result.strike_used == 95.0
    assert result.version
