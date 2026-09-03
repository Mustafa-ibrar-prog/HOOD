"""Phase 26, Part 8/15 — quality-rule detectors: each rule fires on a
deliberately malformed fixture and stays silent on a clean one. No rule
repairs anything -- these tests assert flags, never mutated data."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.data.source_profile import DataProvenance
from src.data.store_interfaces import ProvenancedObservation
from src.data.timestamp_model import EventTimestamps
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore, build_contract_identity, build_provenance
from src.options.phase26_lean_sample_parser import LeanContractFileMeta
from src.options.phase26_quality_rules import (
    check_bid_gt_ask,
    check_duplicate_observations,
    check_invalid_expirations,
    check_missing_timestamps,
    check_negative_open_interest,
    check_negative_or_zero_prices,
    check_negative_volume,
    check_ohlc_violations,
    check_option_type_mismatch,
    check_timestamp_ordering,
    check_zero_or_invalid_strikes,
    run_all_quality_checks,
)

RETRIEVAL = datetime(2026, 9, 3, tzinfo=timezone.utc)


def _obs(key, field, value, ts):
    return ProvenancedObservation(key=key, field=field, value=value,
                                   timestamps=EventTimestamps(event_time=ts, observation_time=ts),
                                   provenance=DataProvenance.OBSERVED, source="test")


def _contract(strike=100.0, expiration=date(2016, 1, 15)):
    p = build_provenance(retrieval_timestamp=RETRIEVAL, adjustment_status="x")
    meta = LeanContractFileMeta("AAPL", "call", strike, expiration, "quote", "american", None)
    return build_contract_identity(meta, p)


def _empty_store(contracts=None, lifecycles=None, quotes=None, trades=None, oi=None):
    return InMemoryLeanSampleStore(
        contracts=contracts or {}, lifecycles=lifecycles or {}, quotes=quotes or {},
        trades=trades or {}, open_interest=oi or {}, underlying={},
    )


def test_bid_gt_ask_fires_on_a_crossed_market():
    cid = "AAPL_call_100.0000_2016-01-15"
    ts = datetime(2015, 1, 2)
    store = _empty_store(quotes={cid: [_obs(cid, "bid", 20.0, ts), _obs(cid, "ask", 15.0, ts)]})
    flags = check_bid_gt_ask(store)
    assert len(flags) == 1
    assert flags[0].rule == "bid_gt_ask"


def test_bid_gt_ask_silent_on_a_normal_market():
    cid = "AAPL_call_100.0000_2016-01-15"
    ts = datetime(2015, 1, 2)
    store = _empty_store(quotes={cid: [_obs(cid, "bid", 10.0, ts), _obs(cid, "ask", 11.0, ts)]})
    assert check_bid_gt_ask(store) == []


def test_bid_gt_ask_silent_when_one_side_is_none():
    """A genuinely one-sided market (real phenomenon this phase found)
    must not be flagged as bid>ask."""
    cid = "AAPL_call_100.0000_2016-01-15"
    ts = datetime(2015, 1, 2)
    store = _empty_store(quotes={cid: [_obs(cid, "bid", None, ts), _obs(cid, "ask", 1.0, ts)]})
    assert check_bid_gt_ask(store) == []


def test_negative_price_fires():
    cid = "AAPL_call_100.0000_2016-01-15"
    ts = datetime(2015, 1, 2)
    store = _empty_store(quotes={cid: [_obs(cid, "bid", -1.0, ts)]})
    flags = check_negative_or_zero_prices(store)
    assert any(f.rule == "negative_price" for f in flags)


def test_negative_volume_fires():
    cid = "SPY_call_430.0000_2023-09-01"
    ts = datetime(2023, 8, 3)
    store = _empty_store(trades={cid: [_obs(cid, "volume", -5.0, ts)]})
    assert len(check_negative_volume(store)) == 1


def test_negative_open_interest_fires():
    cid = "AAPL_call_100.0000_2015-01-17"
    ts = datetime(2014, 6, 6)
    store = _empty_store(oi={cid: [_obs(cid, "open_interest", -1.0, ts)]})
    assert len(check_negative_open_interest(store)) == 1


def test_zero_strike_fires():
    c = _contract(strike=0.0)
    store = _empty_store(contracts={c.option_id: c})
    assert len(check_zero_or_invalid_strikes(store)) == 1


def test_positive_strike_is_silent():
    c = _contract(strike=100.0)
    store = _empty_store(contracts={c.option_id: c})
    assert check_zero_or_invalid_strikes(store) == []


def test_option_type_mismatch_fires_on_bad_call_put():
    p = build_provenance(retrieval_timestamp=RETRIEVAL, adjustment_status="x")
    from src.options.historical_data_interfaces import ContractIdentity
    bad = ContractIdentity(option_id="X", underlying_symbol="AAPL", call_put="straddle", strike=100.0,
                            expiration=date(2016, 1, 15), multiplier=100, exercise_style="american",
                            contract_status="unknown", provenance=p)
    store = _empty_store(contracts={"X": bad})
    flags = check_option_type_mismatch(store)
    assert any(f.rule == "option_type_mismatch" for f in flags)


def test_ohlc_violation_fires_when_high_below_close():
    cid = "SPY_call_430.0000_2023-09-01"
    ts = datetime(2023, 8, 3, 10, 0)
    store = _empty_store(trades={cid: [_obs(cid, "open", 10.0, ts), _obs(cid, "high", 9.0, ts),
                                        _obs(cid, "low", 8.0, ts), _obs(cid, "close", 10.0, ts)]})
    flags = check_ohlc_violations(store)
    assert len(flags) == 1


def test_ohlc_valid_bar_is_silent():
    cid = "SPY_call_430.0000_2023-09-01"
    ts = datetime(2023, 8, 3, 10, 0)
    store = _empty_store(trades={cid: [_obs(cid, "open", 10.0, ts), _obs(cid, "high", 12.0, ts),
                                        _obs(cid, "low", 9.0, ts), _obs(cid, "close", 11.0, ts)]})
    assert check_ohlc_violations(store) == []


def test_duplicate_observation_fires():
    cid = "AAPL_call_100.0000_2016-01-15"
    ts = datetime(2015, 1, 2)
    store = _empty_store(quotes={cid: [_obs(cid, "bid", 1.0, ts), _obs(cid, "bid", 1.0, ts)]})
    flags = check_duplicate_observations(store)
    assert len(flags) == 1
    assert flags[0].severity == "warning"


def test_missing_timestamp_fires():
    cid = "AAPL_call_100.0000_2016-01-15"
    obs = ProvenancedObservation(key=cid, field="bid", value=1.0, timestamps=EventTimestamps(event_time=None),
                                  provenance=DataProvenance.OBSERVED, source="test")
    store = _empty_store(quotes={cid: [obs]})
    assert len(check_missing_timestamps(store)) == 1


def test_timestamp_ordering_fires_on_out_of_order_rows():
    cid = "AAPL_call_100.0000_2016-01-15"
    store = _empty_store(quotes={cid: [
        _obs(cid, "bid", 1.0, datetime(2015, 1, 5)),
        _obs(cid, "bid", 1.0, datetime(2015, 1, 2)),
    ]})
    assert len(check_timestamp_ordering(store)) == 1


def test_invalid_expiration_fires_when_expiration_precedes_first_observation():
    from src.options.historical_data_interfaces import ContractLifecycle, ContractLifecycleStatus
    c = _contract(expiration=date(2014, 1, 1))
    p = build_provenance(retrieval_timestamp=RETRIEVAL, adjustment_status="x")
    lc = ContractLifecycle(option_id=c.option_id, first_observable_date=date(2015, 1, 1), first_listed_date=None,
                            last_trade_date=date(2015, 6, 1), expiration_date=date(2014, 1, 1),
                            status=ContractLifecycleStatus.UNKNOWN, provenance=p)
    store = _empty_store(contracts={c.option_id: c}, lifecycles={c.option_id: lc})
    assert len(check_invalid_expirations(store)) == 1


def test_run_all_quality_checks_on_a_clean_store_only_flags_the_multiplier_convention():
    c = _contract()
    ts = datetime(2015, 1, 2)
    store = _empty_store(
        contracts={c.option_id: c},
        quotes={c.option_id: [_obs(c.option_id, "bid", 10.0, ts), _obs(c.option_id, "ask", 11.0, ts)]},
    )
    flags = run_all_quality_checks(store)
    assert all(f.rule == "multiplier_not_source_confirmed" for f in flags)
