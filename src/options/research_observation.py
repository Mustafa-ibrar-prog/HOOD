"""Phase 19, Part 3 — the option-contract RESEARCH observation: one
(contract, trading day) row carrying everything a discovery-stage
analysis needs, causal by construction.

Distinct from Phase 18's `OptionChainObservation` (a single point-in-time
quote/bar with per-field provenance, live-quote-shaped) -- this is a
research-panel ROW: option OHLC for that day, a REFERENCE to the
underlying's own OHLC for the same day (not embedded duplicate data --
see `underlying_close` below), moneyness, DTE, and (for a real forward-
return computation) the holding-period return over each preregistered
horizon. Every field is derived from OBSERVED daily bars only -- no
solver, no assumed volatility, no synthesized price.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from src.options.expiration import DTEBucket, bucket_dte, days_to_expiration
from src.options.instrument import OptionContract
from src.options.moneyness import MoneynessBucket, MoneynessObservation
from src.options.price_history import OptionPriceBar


@dataclass(frozen=True)
class OptionResearchObservation:
    contract: OptionContract
    option_bar: OptionPriceBar  # this contract's OHLC for `option_bar.date`
    underlying_close: float  # the underlying's OWN close for the SAME date -- a reference value, not a duplicated bar object
    dte: int
    dte_bucket: DTEBucket
    moneyness: MoneynessObservation
    forward_returns: dict[int, float | None] = field(default_factory=dict)  # horizon_bars -> future_option_return value (see price_history.future_option_return) -- None where the horizon runs past the observed series' end

    @property
    def observation_date(self) -> date:
        return self.option_bar.date

    @classmethod
    def build(
        cls, *, contract: OptionContract, option_bar: OptionPriceBar, underlying_close: float,
        forward_returns: dict[int, float | None] | None = None,
    ) -> "OptionResearchObservation":
        dte = days_to_expiration(option_bar.date, contract.expiration)
        moneyness = MoneynessObservation.compute(underlying_price=underlying_close, strike=contract.strike, call_put=contract.call_put)
        return cls(
            contract=contract, option_bar=option_bar, underlying_close=underlying_close, dte=dte,
            dte_bucket=bucket_dte(dte), moneyness=moneyness, forward_returns=dict(forward_returns or {}),
        )


def build_research_series(
    *, contract: OptionContract, option_bars: list[OptionPriceBar], underlying_closes_by_date: dict[date, float],
    horizons: tuple[int, ...],
) -> list[OptionResearchObservation]:
    """Builds one `OptionResearchObservation` per option bar whose date
    has a matching underlying close. A bar with NO matching underlying
    close (e.g. a data gap) is silently DROPPED, never given a
    fabricated/interpolated underlying price -- see
    tests/test_options_research_observation.py."""
    from src.options.price_history import future_option_return

    forward_by_horizon = {h: future_option_return(option_bars, h) for h in horizons}
    out: list[OptionResearchObservation] = []
    for i, bar in enumerate(option_bars):
        underlying_close = underlying_closes_by_date.get(bar.date)
        if underlying_close is None:
            continue
        forward_returns = {h: forward_by_horizon[h][i] for h in horizons}
        out.append(OptionResearchObservation.build(contract=contract, option_bar=bar, underlying_close=underlying_close, forward_returns=forward_returns))
    return out
