"""Phase 26, Part 6/15 — execution realism grading and spread stats,
tested against constructed fixtures covering each grade."""

from __future__ import annotations

from datetime import datetime

import pytest

from src.data.source_profile import DataProvenance
from src.data.store_interfaces import ProvenancedObservation
from src.data.timestamp_model import EventTimestamps
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.phase26_execution_realism import ExecutionRealismGrade, build_execution_realism_report


def _obs(key, field, value, ts):
    return ProvenancedObservation(key=key, field=field, value=value,
                                   timestamps=EventTimestamps(event_time=ts, observation_time=ts),
                                   provenance=DataProvenance.OBSERVED, source="test")


def _store(quotes=None, trades=None):
    return InMemoryLeanSampleStore(contracts={}, lifecycles={}, quotes=quotes or {}, trades=trades or {}, open_interest={}, underlying={})


def test_grade_f_when_nothing_present():
    store = _store()
    rep = build_execution_realism_report(store, "nonexistent")
    assert rep.grade == ExecutionRealismGrade.F


def test_grade_a_when_quotes_and_trades_both_present():
    cid = "SPY_call_430.0000_2023-09-01"
    ts = datetime(2023, 8, 3, 9, 30)
    store = _store(
        quotes={cid: [_obs(cid, "bid", 10.0, ts), _obs(cid, "ask", 10.5, ts)]},
        trades={cid: [_obs(cid, "price", 10.2, ts)]},
    )
    rep = build_execution_realism_report(store, cid)
    assert rep.grade == ExecutionRealismGrade.A
    assert rep.mean_spread_dollars == pytest.approx(0.5)
    assert rep.mean_spread_pct_of_mid == pytest.approx(0.5 / 10.25)


def test_grade_b_when_only_quotes_present():
    cid = "SPY_call_430.0000_2023-09-01"
    ts = datetime(2023, 8, 3, 9, 30)
    store = _store(quotes={cid: [_obs(cid, "bid", 10.0, ts), _obs(cid, "ask", 10.5, ts)]})
    rep = build_execution_realism_report(store, cid)
    assert rep.grade == ExecutionRealismGrade.B


def test_grade_c_when_only_trades_present():
    cid = "SPY_call_430.0000_2023-09-01"
    ts = datetime(2023, 8, 3, 9, 30)
    store = _store(trades={cid: [_obs(cid, "price", 10.2, ts)]})
    rep = build_execution_realism_report(store, cid)
    assert rep.grade == ExecutionRealismGrade.C


def test_trades_inside_spread_rate_detects_a_trade_outside_the_quoted_spread():
    cid = "SPY_call_430.0000_2023-09-01"
    ts = datetime(2023, 8, 3, 9, 30)
    store = _store(
        quotes={cid: [_obs(cid, "bid", 10.0, ts), _obs(cid, "ask", 10.5, ts)]},
        trades={cid: [_obs(cid, "price", 20.0, ts)]},  # a trade priced far outside the quoted spread
    )
    rep = build_execution_realism_report(store, cid)
    assert rep.trades_inside_spread_rate == 0.0


def test_one_sided_quote_row_correctly_excluded_from_the_spread_average_but_counted_in_availability():
    """A real phenomenon this phase found (an unquoted side represented
    as None) must lower quote_availability_rate and count toward
    zero_or_invalid_quote_rate, without corrupting mean_spread_dollars."""
    cid = "AAPL_call_1000.0000_2015-01-17"
    t1, t2 = datetime(2014, 6, 5), datetime(2014, 6, 6)
    store = _store(quotes={cid: [
        _obs(cid, "bid", 1.0, t1), _obs(cid, "ask", 1.1, t1),  # a normal, two-sided row
        _obs(cid, "ask", 0.03, t2),  # a real one-sided row -- bid genuinely absent (no bid observation at all)
    ]})
    rep = build_execution_realism_report(store, cid)
    assert rep.n_quote_snapshots == 2
    assert rep.quote_availability_rate == pytest.approx(0.5)
    assert rep.mean_spread_dollars == pytest.approx(0.1)  # only the valid two-sided row contributes


def test_zero_bid_and_ask_counts_as_invalid_not_a_real_free_spread():
    cid = "AAPL_call_100.0000_2016-01-15"
    ts = datetime(2015, 1, 2)
    store = _store(quotes={cid: [_obs(cid, "bid", 0.0, ts), _obs(cid, "ask", 0.0, ts)]})
    rep = build_execution_realism_report(store, cid)
    assert rep.zero_or_invalid_quote_rate == pytest.approx(1.0)
    assert rep.mean_spread_dollars is None
