"""Phase 18, Part 22 — chain representation, observed-vs-derived-vs-
unavailable field status tests."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.options.chain import OptionChainObservation, OptionsFieldStatus
from src.options.instrument import OptionContract

CONTRACT = OptionContract(underlying_symbol="AAPL", option_id="dcec1c7b-45a3-40ce-b9e4-b02a82090d3c", call_put="call", strike=230.0, expiration=date(2026, 9, 18))


def test_from_live_quote_marks_present_fields_observed():
    obs = OptionChainObservation.from_live_quote(
        CONTRACT, observation_timestamp=datetime(2026, 9, 2, 19, 59, 59, tzinfo=timezone.utc),
        bid=94.30, ask=97.15, last=95.725, volume=2, open_interest=1709,
    )
    assert obs.status_of("bid") == OptionsFieldStatus.OBSERVED
    assert obs.status_of("ask") == OptionsFieldStatus.OBSERVED
    assert obs.status_of("volume") == OptionsFieldStatus.OBSERVED
    assert obs.status_of("open_interest") == OptionsFieldStatus.OBSERVED


def test_from_live_quote_marks_missing_fields_unavailable():
    obs = OptionChainObservation.from_live_quote(
        CONTRACT, observation_timestamp=datetime(2026, 9, 2, tzinfo=timezone.utc),
        bid=94.30, ask=97.15, last=95.725, volume=None, open_interest=None,
    )
    assert obs.status_of("volume") == OptionsFieldStatus.UNAVAILABLE
    assert obs.status_of("open_interest") == OptionsFieldStatus.UNAVAILABLE
    assert obs.volume is None  # never coerced to 0


def test_midpoint_derived_only_when_both_observed():
    obs = OptionChainObservation.from_live_quote(CONTRACT, observation_timestamp=datetime(2026, 9, 2, tzinfo=timezone.utc), bid=94.30, ask=97.15, last=None, volume=None, open_interest=None)
    assert obs.midpoint == (94.30 + 97.15) / 2


def test_midpoint_none_when_bid_or_ask_unavailable():
    obs = OptionChainObservation.from_live_quote(CONTRACT, observation_timestamp=datetime(2026, 9, 2, tzinfo=timezone.utc), bid=None, ask=97.15, last=95.0, volume=None, open_interest=None)
    assert obs.midpoint is None


def test_from_historical_bar_bid_ask_volume_oi_all_unavailable():
    """Confirms the real capability finding: historical bars never carry
    bid/ask/volume/open_interest."""
    obs = OptionChainObservation.from_historical_bar(CONTRACT, observation_timestamp=datetime(2021, 12, 1, tzinfo=timezone.utc), close_price=3.53)
    assert obs.status_of("bid") == OptionsFieldStatus.UNAVAILABLE
    assert obs.status_of("ask") == OptionsFieldStatus.UNAVAILABLE
    assert obs.status_of("volume") == OptionsFieldStatus.UNAVAILABLE
    assert obs.status_of("open_interest") == OptionsFieldStatus.UNAVAILABLE
    assert obs.status_of("last") == OptionsFieldStatus.OBSERVED
    assert obs.last == 3.53


def test_unrequested_field_status_defaults_to_unavailable():
    obs = OptionChainObservation(contract=CONTRACT, observation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), underlying_timestamp=None, source="test")
    assert obs.status_of("bid") == OptionsFieldStatus.UNAVAILABLE
    assert obs.status_of("anything_not_tracked") == OptionsFieldStatus.UNAVAILABLE
