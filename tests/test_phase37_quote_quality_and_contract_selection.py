"""Phase 37, Part 10-13 — quote quality flags and deterministic contract
selection."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from src.research_recorder.contract_selection import (
    ContractSelectionBounds,
    DteBucket,
    MoneynessBucket,
    select_observation_contracts,
)
from src.research_recorder.normalized_observation import build_normalized_option_observation
from src.research_recorder.quote_quality import QualityFlag, assess_quote_quality


def _now():
    return datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc)


def _obs(**overrides):
    defaults = dict(
        option_id="opt-1", underlying="AAPL", observation_cycle_id="c1", observation_timestamp=_now(),
        market_timezone="America/New_York", quote_row={"bid_price": "1.0", "ask_price": "1.05", "updated_at": _now().isoformat()},
        chain_row={"type": "call", "strike_price": "230.0", "expiration_date": "2026-10-01", "state": "active", "tradability": "tradable"},
        underlying_price=230.0,
    )
    defaults.update(overrides)
    return build_normalized_option_observation(**defaults)


# --- Quote quality --------------------------------------------------------------------------


def test_clean_observation_has_no_flags():
    assessment = assess_quote_quality(_obs(), now=_now())
    assert assessment.is_clean


def test_missing_bid_flagged():
    obs = _obs(quote_row={"ask_price": "1.05"})
    assessment = assess_quote_quality(obs, now=_now())
    assert QualityFlag.MISSING_BID in assessment.flags


def test_missing_ask_flagged():
    obs = _obs(quote_row={"bid_price": "1.0"})
    assessment = assess_quote_quality(obs, now=_now())
    assert QualityFlag.MISSING_ASK in assessment.flags


def test_non_positive_bid_flagged():
    obs = _obs(quote_row={"bid_price": "0", "ask_price": "1.05"})
    assessment = assess_quote_quality(obs, now=_now())
    assert QualityFlag.BID_NOT_POSITIVE in assessment.flags


def test_crossed_market_flagged():
    obs = _obs(quote_row={"bid_price": "1.10", "ask_price": "1.00"})
    assessment = assess_quote_quality(obs, now=_now())
    assert QualityFlag.CROSSED_MARKET in assessment.flags


def test_extreme_spread_flagged():
    obs = _obs(quote_row={"bid_price": "1.0", "ask_price": "3.0"})
    assessment = assess_quote_quality(obs, now=_now(), extreme_spread_pct=0.5)
    assert QualityFlag.EXTREME_SPREAD in assessment.flags


def test_stale_timestamp_flagged():
    stale = (_now() - timedelta(seconds=200)).isoformat()
    obs = _obs(quote_row={"bid_price": "1.0", "ask_price": "1.05", "updated_at": stale})
    assessment = assess_quote_quality(obs, now=_now(), max_quote_age_seconds=90.0)
    assert QualityFlag.STALE_TIMESTAMP in assessment.flags


def test_malformed_contract_flagged_when_chain_row_missing():
    obs = _obs(chain_row=None)
    assessment = assess_quote_quality(obs, now=_now())
    assert QualityFlag.MALFORMED_CONTRACT in assessment.flags


def test_expired_contract_flagged():
    obs = _obs(chain_row={"type": "call", "strike_price": "230.0", "expiration_date": "2020-01-01"})
    assessment = assess_quote_quality(obs, now=_now())
    assert QualityFlag.EXPIRED_CONTRACT in assessment.flags


def test_inactive_contract_flagged():
    obs = _obs(chain_row={"type": "call", "strike_price": "230.0", "expiration_date": "2026-10-01", "state": "inactive"})
    assessment = assess_quote_quality(obs, now=_now())
    assert QualityFlag.INACTIVE_CONTRACT in assessment.flags


def test_duplicate_observation_flagged_when_told():
    assessment = assess_quote_quality(_obs(), now=_now(), is_duplicate=True)
    assert QualityFlag.DUPLICATE_OBSERVATION in assessment.flags


def test_bad_observation_is_flagged_never_deleted():
    """The observation object itself is untouched -- only the assessment
    carries flags. This test exists to lock in that quote_quality never
    mutates or drops the input."""
    obs = _obs(quote_row={"bid_price": "1.10", "ask_price": "1.00"})
    assessment = assess_quote_quality(obs, now=_now())
    assert obs.bid == 1.10 and obs.ask == 1.00  # unchanged
    assert not assessment.is_clean


# --- Contract selection -----------------------------------------------------------------------


def _chain(now, strikes=(200, 210, 220, 230, 240, 250, 260), dtes=(7, 20, 30, 45, 60, 80)):
    rows = []
    for strike in strikes:
        for dte_days in dtes:
            exp = (now.date() + timedelta(days=dte_days)).isoformat()
            rows.append({"id": f"call-{strike}-{dte_days}", "type": "call", "strike_price": str(strike), "expiration_date": exp, "state": "active", "tradability": "tradable"})
            rows.append({"id": f"put-{strike}-{dte_days}", "type": "put", "strike_price": str(strike), "expiration_date": exp, "state": "active", "tradability": "tradable"})
    return rows


def test_selection_covers_all_nine_buckets_per_option_type():
    now = _now()
    rows = _chain(now)
    selected = select_observation_contracts(rows, underlying_price=230.0, now=now, market_timezone="America/New_York")
    buckets = {(c.option_type, c.dte_bucket, c.moneyness_bucket) for c in selected}
    assert len(buckets) == 18  # 3 DTE x 3 moneyness x 2 option types


def test_selection_is_deterministic():
    now = _now()
    rows = _chain(now)
    a = select_observation_contracts(rows, underlying_price=230.0, now=now, market_timezone="America/New_York")
    b = select_observation_contracts(rows, underlying_price=230.0, now=now, market_timezone="America/New_York")
    assert [c.chain_row["id"] for c in a] == [c.chain_row["id"] for c in b]


def test_selection_never_picks_more_than_one_per_bucket():
    now = _now()
    rows = _chain(now)
    selected = select_observation_contracts(rows, underlying_price=230.0, now=now, market_timezone="America/New_York")
    keys = [(c.option_type, c.dte_bucket, c.moneyness_bucket) for c in selected]
    assert len(keys) == len(set(keys))


def test_selection_respects_max_contracts_per_symbol():
    now = _now()
    rows = _chain(now)
    bounds = ContractSelectionBounds(max_contracts_per_symbol_per_cycle=5)
    selected = select_observation_contracts(rows, underlying_price=230.0, now=now, market_timezone="America/New_York", bounds=bounds)
    assert len(selected) <= 5


def test_selection_excludes_out_of_bounds_dte():
    now = _now()
    rows = _chain(now, dtes=(200,))  # way beyond max_dte=90 default
    selected = select_observation_contracts(rows, underlying_price=230.0, now=now, market_timezone="America/New_York")
    assert selected == []


def test_selection_excludes_out_of_bounds_moneyness():
    now = _now()
    rows = _chain(now, strikes=(1000,))  # far OTM/ITM beyond the default 20% band
    selected = select_observation_contracts(rows, underlying_price=230.0, now=now, market_timezone="America/New_York")
    assert selected == []


def test_selection_skips_malformed_rows_without_crashing():
    now = _now()
    rows = [{"type": "call"}, {"type": "call", "strike_price": "not-a-number", "expiration_date": "2026-10-01"}]
    selected = select_observation_contracts(rows, underlying_price=230.0, now=now, market_timezone="America/New_York")
    assert selected == []


def test_selection_uses_only_same_cycle_underlying_price():
    """Part 12: 'Do not use future information to select contracts.'
    Passing a different underlying_price changes which strikes land in
    which moneyness bucket -- selection is a pure function of the price
    given, never a stored/later one."""
    now = _now()
    rows = _chain(now)
    low = select_observation_contracts(rows, underlying_price=200.0, now=now, market_timezone="America/New_York")
    high = select_observation_contracts(rows, underlying_price=260.0, now=now, market_timezone="America/New_York")
    low_strikes = {c.chain_row["strike_price"] for c in low}
    high_strikes = {c.chain_row["strike_price"] for c in high}
    assert low_strikes != high_strikes
