"""Phase 26, Part 7/15 — IV/Greeks reconstruction: succeeds only when a
real paired underlying price exists in-sample, and honestly returns
UNAVAILABLE (never a fabricated number) otherwise."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.options.implied_volatility import IVProvenance
from src.options.greeks import GreeksProvenance
from src.options.phase26_dataset_builder import (
    InMemoryLeanSampleStore,
    build_contract_identity,
    build_provenance,
    contract_id_for,
    quote_observations,
    underlying_observations,
)
from src.options.phase26_iv_greeks_certification import reconstruct_iv_and_greeks
from src.options.phase26_lean_sample_parser import LeanContractFileMeta, LeanEquityBar, LeanQuoteRow

RETRIEVAL = datetime(2026, 9, 3, tzinfo=timezone.utc)


def _build_store_with_real_aapl_example():
    p = build_provenance(retrieval_timestamp=RETRIEVAL, adjustment_status="x")
    meta = LeanContractFileMeta("AAPL", "call", 100.0, date(2016, 1, 15), "quote", "american", None)
    contract = build_contract_identity(meta, p)
    cid = contract_id_for(meta)

    quote_row = LeanQuoteRow(
        timestamp=datetime(2015, 1, 2), bid_open=18.1, bid_high=18.6, bid_low=16.2, bid_close=17.55,
        last_bid_size=224, ask_open=18.35, ask_high=20.35, ask_low=16.7, ask_close=17.75, last_ask_size=103,
        is_daily_resolution=True,
    )
    equity_bar = LeanEquityBar(date=date(2015, 1, 2), open=111.41, high=111.44, low=107.35, close=109.33, volume=52381530)

    quotes = {cid: quote_observations(cid, quote_row, ingestion_time=RETRIEVAL)}
    underlying = {"AAPL": underlying_observations("AAPL", equity_bar, ingestion_time=RETRIEVAL)}
    store = InMemoryLeanSampleStore(contracts={cid: contract}, lifecycles={}, quotes=quotes, trades={}, open_interest={}, underlying=underlying)
    return store, contract


def test_reconstruction_succeeds_with_a_real_paired_underlying_price():
    store, contract = _build_store_with_real_aapl_example()
    attempt = reconstruct_iv_and_greeks(store, contract, date(2015, 1, 2), underlying_symbol="AAPL")
    assert attempt.underlying_price_source == "real_ingested_equity_bar"
    assert attempt.iv.provenance == IVProvenance.DERIVED
    assert 0.15 < attempt.iv.value < 0.60
    assert attempt.greeks.provenance == GreeksProvenance.DERIVED_FROM_MODEL
    assert 0.0 < attempt.greeks.delta < 1.0
    assert attempt.iv.derived_metadata.pricing_model == "black_scholes"
    assert attempt.greeks.derived_metadata.model == "black_scholes"


def test_reconstruction_is_honestly_unavailable_with_no_underlying_price():
    store, contract = _build_store_with_real_aapl_example()
    # ask for a date with no real equity bar in-sample
    attempt = reconstruct_iv_and_greeks(store, contract, date(2020, 1, 1), underlying_symbol="AAPL")
    assert attempt.underlying_price_source == "not_available_in_sample"
    assert attempt.iv.value is None
    assert attempt.iv.provenance == IVProvenance.UNAVAILABLE
    assert attempt.greeks.delta is None
    assert attempt.greeks.provenance == GreeksProvenance.UNAVAILABLE


def test_reconstruction_is_unavailable_when_the_quote_itself_is_missing():
    store, contract = _build_store_with_real_aapl_example()
    attempt = reconstruct_iv_and_greeks(store, contract, date(2015, 1, 2), underlying_symbol="NONEXISTENT_SYMBOL")
    assert attempt.iv.provenance == IVProvenance.UNAVAILABLE


def test_reconstruction_never_produces_observed_provenance():
    """A reconstructed value must NEVER be mistaken for a vendor-
    observed one (Part 7's core distinction)."""
    store, contract = _build_store_with_real_aapl_example()
    attempt = reconstruct_iv_and_greeks(store, contract, date(2015, 1, 2), underlying_symbol="AAPL")
    assert attempt.iv.provenance != IVProvenance.OBSERVED
    assert attempt.greeks.provenance != GreeksProvenance.OBSERVED_FROM_SOURCE
