"""Phase 26, Part 9/15 — PIT/lookahead certification, including the
explicit adversarial injection tests Part 9 requires."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.data.source_profile import DataProvenance
from src.data.store_interfaces import ProvenancedObservation
from src.data.timestamp_model import EventTimestamps
from src.options.historical_data_interfaces import ContractLifecycle, ContractLifecycleStatus
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore, build_contract_identity, build_provenance
from src.options.phase26_lean_sample_parser import LeanContractFileMeta
from src.options.phase26_pit_certification import (
    adversarial_future_observation_is_rejected,
    adversarial_missing_causal_timestamp_is_rejected,
    contract_visible_before_first_observation_is_a_violation,
    contracts_with_any_knowable_quote_as_of,
    knowable_observations_as_of,
)

RETRIEVAL = datetime(2026, 9, 3, tzinfo=timezone.utc)


def _obs(key, field, value, ts):
    return ProvenancedObservation(key=key, field=field, value=value,
                                   timestamps=EventTimestamps(event_time=ts, observation_time=ts),
                                   provenance=DataProvenance.OBSERVED, source="test")


def test_adversarial_future_observation_is_correctly_rejected():
    """Part 9's explicit requirement: deliberately inject future
    information and confirm the machinery rejects it."""
    assert adversarial_future_observation_is_rejected(as_of=datetime(2015, 6, 1), future_event_time=datetime(2015, 7, 1)) is True


def test_adversarial_past_observation_is_not_rejected():
    """The adversarial helper must not be a rubber stamp -- a genuinely
    past observation must NOT be rejected."""
    assert adversarial_future_observation_is_rejected(as_of=datetime(2015, 7, 1), future_event_time=datetime(2015, 6, 1)) is False


def test_adversarial_missing_causal_timestamp_is_rejected():
    assert adversarial_missing_causal_timestamp_is_rejected(as_of=datetime(2015, 6, 1)) is True


def test_knowable_observations_excludes_future_rows():
    cid = "AAPL_call_100.0000_2016-01-15"
    obs = [_obs(cid, "bid", 1.0, datetime(2015, 1, 1)), _obs(cid, "bid", 2.0, datetime(2015, 12, 31))]
    knowable = knowable_observations_as_of(obs, as_of=datetime(2015, 6, 1))
    assert len(knowable) == 1
    assert knowable[0].value == 1.0


def test_knowable_observations_excludes_rows_with_no_event_time():
    cid = "AAPL_call_100.0000_2016-01-15"
    no_ts = ProvenancedObservation(key=cid, field="bid", value=1.0, timestamps=EventTimestamps(event_time=None),
                                    provenance=DataProvenance.OBSERVED, source="test")
    assert knowable_observations_as_of([no_ts], as_of=datetime(2099, 1, 1)) == []


def test_contracts_with_any_knowable_quote_as_of():
    c1 = "AAPL_call_100.0000_2016-01-15"
    c2 = "AAPL_call_110.0000_2016-01-15"
    store = InMemoryLeanSampleStore(
        contracts={}, lifecycles={},
        quotes={
            c1: [_obs(c1, "bid", 1.0, datetime(2015, 1, 1))],
            c2: [_obs(c2, "bid", 1.0, datetime(2015, 12, 1))],
        },
        trades={}, open_interest={}, underlying={},
    )
    knowable = contracts_with_any_knowable_quote_as_of(store, as_of=datetime(2015, 6, 1))
    assert knowable == {c1}


def test_contract_visible_before_first_observation_check_passes_for_real_gap():
    p = build_provenance(retrieval_timestamp=RETRIEVAL, adjustment_status="x")
    meta = LeanContractFileMeta("AAPL", "call", 100.0, date(2016, 1, 15), "quote", "american", None)
    c = build_contract_identity(meta, p)
    lc = ContractLifecycle(option_id=c.option_id, first_observable_date=date(2015, 6, 1), first_listed_date=None,
                            last_trade_date=date(2015, 12, 1), expiration_date=date(2016, 1, 15),
                            status=ContractLifecycleStatus.UNKNOWN, provenance=p)
    store = InMemoryLeanSampleStore(contracts={c.option_id: c}, lifecycles={c.option_id: lc}, quotes={},
                                     trades={}, open_interest={}, underlying={})
    # probing well before first_observable_date -- there is genuinely no quote data, so this must pass
    assert contract_visible_before_first_observation_is_a_violation(store, c.option_id, date(2015, 1, 1)) is True


def test_contract_visible_before_first_observation_returns_false_when_lifecycle_unknown():
    store = InMemoryLeanSampleStore(contracts={}, lifecycles={}, quotes={}, trades={}, open_interest={}, underlying={})
    assert contract_visible_before_first_observation_is_a_violation(store, "nonexistent", date(2015, 1, 1)) is False
