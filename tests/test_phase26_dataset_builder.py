"""Phase 26, Part 12/15 — the concrete Protocol implementation:
provenance, contract identity, lifecycle, and the in-memory store."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.options.historical_data_interfaces import ContractLifecycleStatus, HistoricalOrLive
from src.options.phase26_dataset_builder import (
    MULTIPLIER_SOURCE_CONFIRMED,
    STANDARD_US_EQUITY_OPTION_MULTIPLIER,
    InMemoryLeanSampleStore,
    build_contract_identity,
    build_contract_lifecycle,
    build_provenance,
    contract_id_for,
    open_interest_observation,
    quote_observations,
    trade_observations,
)
from src.options.phase26_lean_sample_parser import (
    LeanContractFileMeta,
    LeanOpenInterestRow,
    LeanQuoteRow,
    LeanTradeRow,
)

RETRIEVAL_TS = datetime(2026, 9, 3, tzinfo=timezone.utc)


def _meta(**overrides) -> LeanContractFileMeta:
    base = dict(underlying_symbol="AAPL", right="call", strike=100.0, expiration=date(2016, 1, 15),
                tick_type="quote", option_style="american", file_date=None)
    base.update(overrides)
    return LeanContractFileMeta(**base)


def test_contract_id_is_deterministic_and_human_readable():
    m = _meta()
    assert contract_id_for(m) == "AAPL_call_100.0000_2016-01-15"
    assert contract_id_for(m) == contract_id_for(_meta())


def test_provenance_marks_historical_and_observed():
    p = build_provenance(retrieval_timestamp=RETRIEVAL_TS, adjustment_status="unknown")
    assert p.historical_or_live == HistoricalOrLive.HISTORICAL
    assert p.interpolation_flag is False
    assert p.retrieval_timestamp == RETRIEVAL_TS


def test_multiplier_is_a_flagged_convention_not_a_verified_field():
    """Part 3: never silently present an assumption as a confirmed
    field."""
    assert MULTIPLIER_SOURCE_CONFIRMED is False
    p = build_provenance(retrieval_timestamp=RETRIEVAL_TS, adjustment_status="x")
    identity = build_contract_identity(_meta(), p)
    assert identity.multiplier == STANDARD_US_EQUITY_OPTION_MULTIPLIER == 100


def test_contract_identity_exercise_style_is_source_confirmed():
    p = build_provenance(retrieval_timestamp=RETRIEVAL_TS, adjustment_status="x")
    identity = build_contract_identity(_meta(option_style="european"), p)
    assert identity.exercise_style == "european"


def test_lifecycle_status_is_expired_when_today_is_past_expiration():
    p = build_provenance(retrieval_timestamp=RETRIEVAL_TS, adjustment_status="x")
    lc = build_contract_lifecycle(_meta(), [date(2015, 1, 2), date(2015, 6, 1)], p, today=date(2026, 9, 3))
    assert lc.status == ContractLifecycleStatus.EXPIRED
    assert lc.first_observable_date == date(2015, 1, 2)
    assert lc.last_trade_date == date(2015, 6, 1)
    assert lc.first_listed_date is None  # never approximated -- Phase 24's explicit rule, honored here


def test_lifecycle_status_is_unknown_when_not_yet_expired():
    p = build_provenance(retrieval_timestamp=RETRIEVAL_TS, adjustment_status="x")
    lc = build_contract_lifecycle(_meta(expiration=date(2030, 1, 1)), [date(2015, 1, 2)], p, today=date(2026, 9, 3))
    assert lc.status == ContractLifecycleStatus.UNKNOWN


def test_lifecycle_rejects_zero_observed_dates():
    p = build_provenance(retrieval_timestamp=RETRIEVAL_TS, adjustment_status="x")
    with pytest.raises(ValueError):
        build_contract_lifecycle(_meta(), [], p, today=date(2026, 9, 3))


def test_quote_observations_include_bid_and_ask_and_preserve_none():
    row = LeanQuoteRow(
        timestamp=datetime(2015, 1, 2), bid_open=None, bid_high=None, bid_low=None, bid_close=None,
        last_bid_size=0, ask_open=1.0, ask_high=1.0, ask_low=1.0, ask_close=1.0, last_ask_size=5,
        is_daily_resolution=True,
    )
    obs = quote_observations("AAPL_call_100.0000_2016-01-15", row, ingestion_time=RETRIEVAL_TS)
    bid = next(o for o in obs if o.field == "bid")
    ask = next(o for o in obs if o.field == "ask")
    assert bid.value is None
    assert ask.value == 1.0


def test_trade_observations_include_price_and_volume():
    row = LeanTradeRow(timestamp=datetime(2023, 8, 3, 10, 23), open=22.33, high=22.33, low=22.33, close=22.33, volume=1, is_daily_resolution=False)
    obs = trade_observations("SPY_call_430.0000_2023-09-01", row, ingestion_time=RETRIEVAL_TS)
    price = next(o for o in obs if o.field == "price")
    volume = next(o for o in obs if o.field == "volume")
    assert price.value == pytest.approx(22.33)
    assert volume.value == 1.0


def test_open_interest_observation():
    row = LeanOpenInterestRow(timestamp=datetime(2014, 6, 6), open_interest=9325, is_daily_resolution=True)
    obs = open_interest_observation("AAPL_call_1000.0000_2015-01-17", row, ingestion_time=RETRIEVAL_TS)
    assert obs.field == "open_interest"
    assert obs.value == 9325.0


def test_in_memory_store_returns_none_and_empty_for_missing_keys():
    store = InMemoryLeanSampleStore(contracts={}, lifecycles={}, quotes={}, trades={}, open_interest={}, underlying={})
    assert store.get_contract("nonexistent") is None
    assert store.get_lifecycle("nonexistent") is None
    assert store.load_quotes("nonexistent") == []
    assert store.load_trades("nonexistent") == []
    assert store.load_open_interest("nonexistent") == []
    assert store.load_underlying("nonexistent") == []


def test_list_contracts_for_expiration_filters_correctly():
    p = build_provenance(retrieval_timestamp=RETRIEVAL_TS, adjustment_status="x")
    c1 = build_contract_identity(_meta(strike=100.0), p)
    c2 = build_contract_identity(_meta(strike=110.0), p)
    c3 = build_contract_identity(_meta(strike=100.0, expiration=date(2017, 1, 20)), p)
    store = InMemoryLeanSampleStore(
        contracts={c1.option_id: c1, c2.option_id: c2, c3.option_id: c3},
        lifecycles={}, quotes={}, trades={}, open_interest={}, underlying={},
    )
    results = store.list_contracts_for_expiration("AAPL", date(2016, 1, 15))
    assert {c.option_id for c in results} == {c1.option_id, c2.option_id}
