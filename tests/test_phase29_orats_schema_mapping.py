"""Phase 29, Part 1/17 — raw ORATS row -> normalized type mapping."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.options.historical_data_interfaces import ContractLifecycleStatus, HistoricalOrLive
from src.options.orats_schema_mapping import (
    MULTIPLIER_SOURCE_CONFIRMED,
    ORATS_SOURCE,
    STANDARD_US_EQUITY_OPTION_MULTIPLIER,
    build_contract_identity_from_strike_row,
    build_contract_lifecycle,
    build_orats_provenance,
    contract_id_for,
    map_strike_row_to_observations,
)
from tests.orats_fixtures import SYNTHETIC_AAPL_ONE_SIDED_ROW, SYNTHETIC_AAPL_STRIKES_20211201

RETRIEVAL = datetime(2026, 9, 4, tzinfo=timezone.utc)


def test_contract_id_is_deterministic():
    from datetime import date
    a = contract_id_for("AAPL", "call", 150.0, date(2022, 1, 21))
    b = contract_id_for("AAPL", "call", 150.0, date(2022, 1, 21))
    assert a == b == "AAPL_call_150.0000_2022-01-21"


def test_provenance_marks_orats_source_and_historical():
    p = build_orats_provenance(retrieval_timestamp=RETRIEVAL)
    assert p.source == ORATS_SOURCE == "orats"
    assert p.historical_or_live == HistoricalOrLive.HISTORICAL
    assert p.interpolation_flag is False


def test_multiplier_is_flagged_convention_not_confirmed():
    assert MULTIPLIER_SOURCE_CONFIRMED is False
    p = build_orats_provenance(retrieval_timestamp=RETRIEVAL)
    row = SYNTHETIC_AAPL_STRIKES_20211201[0]
    identity = build_contract_identity_from_strike_row(row, right="call", provenance=p)
    assert identity.multiplier == STANDARD_US_EQUITY_OPTION_MULTIPLIER == 100


def test_contract_identity_exercise_style_is_honestly_none():
    p = build_orats_provenance(retrieval_timestamp=RETRIEVAL)
    row = SYNTHETIC_AAPL_STRIKES_20211201[0]
    identity = build_contract_identity_from_strike_row(row, right="call", provenance=p)
    assert identity.exercise_style is None


def test_build_contract_identity_rejects_invalid_right():
    p = build_orats_provenance(retrieval_timestamp=RETRIEVAL)
    row = SYNTHETIC_AAPL_STRIKES_20211201[0]
    with pytest.raises(ValueError):
        build_contract_identity_from_strike_row(row, right="straddle", provenance=p)


def test_lifecycle_status_expired_when_today_past_expiration():
    from datetime import date
    p = build_orats_provenance(retrieval_timestamp=RETRIEVAL)
    lc = build_contract_lifecycle("X", date(2022, 1, 21), [date(2021, 12, 1)], p, today=date(2026, 9, 4))
    assert lc.status == ContractLifecycleStatus.EXPIRED
    assert lc.first_listed_date is None


def test_lifecycle_rejects_zero_observed_dates():
    from datetime import date
    p = build_orats_provenance(retrieval_timestamp=RETRIEVAL)
    with pytest.raises(ValueError):
        build_contract_lifecycle("X", date(2022, 1, 21), [], p, today=date(2026, 9, 4))


def test_map_strike_row_extracts_all_real_fields_for_call_side():
    row = SYNTHETIC_AAPL_STRIKES_20211201[0]
    event_time = datetime(2021, 12, 1)
    q, t, oi, u = map_strike_row_to_observations(row, right="call", contract_id="X", event_time=event_time, ingestion_time=RETRIEVAL)
    fields = {o.field: o.value for o in q}
    assert fields["bid"] == 5.20
    assert fields["ask"] == 5.35
    assert fields["bid_size"] == 12.0
    assert fields["ask_size"] == 8.0
    assert fields["iv"] == 0.28
    assert fields["delta"] == 0.55
    assert t[0].field == "volume" and t[0].value == 340.0
    assert oi[0].field == "open_interest" and oi[0].value == 5200.0
    assert u.field == "close" and u.value == 165.30


def test_map_strike_row_extracts_put_side_correctly():
    row = SYNTHETIC_AAPL_STRIKES_20211201[0]
    q, t, oi, u = map_strike_row_to_observations(row, right="put", contract_id="X", event_time=datetime(2021, 12, 1), ingestion_time=RETRIEVAL)
    fields = {o.field: o.value for o in q}
    assert fields["bid"] == 2.10
    assert fields["ask"] == 2.25


def test_one_sided_row_never_fabricates_a_missing_bid():
    """A real phenomenon this project already found (Phase 26/27): a
    genuinely absent bid must produce NO observation, never a
    fabricated 0.0."""
    row = SYNTHETIC_AAPL_ONE_SIDED_ROW
    q, t, oi, u = map_strike_row_to_observations(row, right="call", contract_id="X", event_time=datetime(2021, 12, 1), ingestion_time=RETRIEVAL)
    fields = {o.field for o in q}
    assert "bid" not in fields
    assert "bid_size" not in fields
    assert "ask" in fields  # the ask side IS present in this fixture


def test_missing_underlying_price_key_returns_none_not_zero():
    row = dict(SYNTHETIC_AAPL_STRIKES_20211201[0])
    del row["underlyingPrice"]
    q, t, oi, u = map_strike_row_to_observations(row, right="call", contract_id="X", event_time=datetime(2021, 12, 1), ingestion_time=RETRIEVAL)
    assert u is None
