"""Phase 26, Part 7 — IV/Greeks certification against the real ingested
sample.

Finding (real, not assumed): the QuantConnect/Lean sample's own README
schema (quote/trade/openinterest, confirmed by two independent WebFetch
reads this phase and this phase's prior phase) carries NO implied
volatility or Greeks field anywhere -- so there is nothing supplied to
classify as OBSERVED. Part 7's explicit fallback applies directly: "If
Greeks are not supplied but can be deterministically reconstructed...
classify them separately as RECONSTRUCTABLE, not VERIFIED_VENDOR_FIELD."
This module performs that reconstruction, using Phase 18's existing
`IVObservation`/`Greeks` schema (never inventing a parallel one) and this
phase's new `black_scholes.py` solver, ONLY where a real, paired
underlying price is also available in the actually-ingested data (never
backfilled from outside knowledge -- see the SPY note below).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.options.black_scholes import SOLVER_VERSION, BlackScholesInputs, black_scholes_greeks, implied_volatility_bisection
from src.options.greeks import DerivedGreeksMetadata, Greeks, GreeksProvenance
from src.options.historical_data_interfaces import ContractIdentity
from src.options.implied_volatility import DerivedIVMetadata, IVObservation, IVProvenance
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore

PRICING_MODEL = "black_scholes"

# An explicit, external, documented ASSUMPTION -- this source states no
# risk-free rate or dividend yield anywhere. 2% / 1.5% are illustrative,
# roughly-right-order-of-magnitude placeholders for the 2014-2016 US
# rate/AAPL-dividend environment, NOT a value looked up from a verified
# source this phase. Any reconstructed IV/Greeks below is only as
# reliable as this assumption.
ASSUMED_RISK_FREE_RATE = 0.02
ASSUMED_DIVIDEND_YIELD = 0.015


@dataclass(frozen=True)
class ReconstructionAttempt:
    contract_id: str
    as_of_date: date
    underlying_price_source: str  # "real_ingested_equity_bar" | "not_available_in_sample"
    iv: IVObservation
    greeks: Greeks


def reconstruct_iv_and_greeks(
    store: InMemoryLeanSampleStore,
    contract: ContractIdentity,
    as_of_date: date,
    *,
    underlying_symbol: str,
) -> ReconstructionAttempt:
    """Attempts a real reconstruction using only real, already-ingested
    data. Returns IVObservation.unavailable()/Greeks.unavailable() (never
    a fabricated number) whenever a required real input is missing --
    including when no real underlying-price bar exists for `as_of_date`
    in this sample (this phase's honest finding for the SPY 2023-08-03
    slice, whose paired equity daily file stops at 2021-03-31)."""

    contract_id = contract.option_id
    underlying_bars = store.underlying.get(underlying_symbol, [])
    close_obs = [o for o in underlying_bars if o.field == "close" and o.timestamps.event_time.date() == as_of_date]
    if not close_obs:
        return ReconstructionAttempt(contract_id, as_of_date, "not_available_in_sample", IVObservation.unavailable(), Greeks.unavailable())
    underlying_price = close_obs[0].value

    quote_obs = store.quotes.get(contract_id, [])
    bid = next((o.value for o in quote_obs if o.field == "bid" and o.timestamps.event_time.date() == as_of_date), None)
    ask = next((o.value for o in quote_obs if o.field == "ask" and o.timestamps.event_time.date() == as_of_date), None)
    if bid is None or ask is None:
        return ReconstructionAttempt(contract_id, as_of_date, "real_ingested_equity_bar", IVObservation.unavailable(), Greeks.unavailable())
    mid_price = (bid + ask) / 2

    t_years = (contract.expiration - as_of_date).days / 365.0
    if t_years <= 0:
        return ReconstructionAttempt(contract_id, as_of_date, "real_ingested_equity_bar", IVObservation.unavailable(), Greeks.unavailable())

    iv_value = implied_volatility_bisection(
        target_price=mid_price, underlying_price=underlying_price, strike=contract.strike,
        time_to_expiration_years=t_years, risk_free_rate=ASSUMED_RISK_FREE_RATE,
        dividend_yield=ASSUMED_DIVIDEND_YIELD, call_put=contract.call_put,
    )
    if iv_value is None:
        return ReconstructionAttempt(contract_id, as_of_date, "real_ingested_equity_bar", IVObservation.unavailable(), Greeks.unavailable())

    now = datetime(as_of_date.year, as_of_date.month, as_of_date.day)
    iv_obs = IVObservation(
        value=iv_value, provenance=IVProvenance.DERIVED,
        derived_metadata=DerivedIVMetadata(
            pricing_model=PRICING_MODEL, option_price_used=mid_price, underlying_price=underlying_price,
            strike=contract.strike, expiration=contract.expiration, time_to_expiration_years=t_years,
            interest_rate=ASSUMED_RISK_FREE_RATE, dividend_assumption=ASSUMED_DIVIDEND_YIELD,
            solver_version=SOLVER_VERSION, timestamp=now,
        ),
    )

    bs_inputs = BlackScholesInputs(underlying_price, contract.strike, t_years, ASSUMED_RISK_FREE_RATE, iv_value, ASSUMED_DIVIDEND_YIELD)
    g = black_scholes_greeks(bs_inputs, call_put=contract.call_put)
    greeks_obs = Greeks(
        delta=g.delta, gamma=g.gamma, theta=g.theta / 365.0, vega=g.vega / 100.0, rho=g.rho / 100.0,
        provenance=GreeksProvenance.DERIVED_FROM_MODEL,
        derived_metadata=DerivedGreeksMetadata(
            model=PRICING_MODEL,
            inputs={"underlying_price": underlying_price, "strike": contract.strike, "time_to_expiration_years": t_years},
            timestamp=now, volatility_input=iv_value, rate_assumption=ASSUMED_RISK_FREE_RATE,
            dividend_assumption=ASSUMED_DIVIDEND_YIELD, version=SOLVER_VERSION,
        ),
    )
    return ReconstructionAttempt(contract_id, as_of_date, "real_ingested_equity_bar", iv_obs, greeks_obs)
