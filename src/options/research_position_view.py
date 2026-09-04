"""Phase 30, Part 7/17 — the expanded, reporting-ready position view.

Reuse, not reinvention: Phase 18's `src/options/position.py` ALREADY
implements exactly what Part 7 asks for at the risk-structure level --
`OptionsPosition`/`OptionLegPosition` support LONG_CALL/LONG_PUT/
SHORT_CALL/SHORT_PUT (any single long/short call/put leg) and
`analyze_position_risk()` already handles 2-leg same-expiration vertical
spreads, falling back to an explicit `UNSUPPORTED_STRUCTURE` method
string for anything else -- never guessing a max loss/gain it can't
actually determine. This module does NOT re-implement any of that. It
only ADDS the reporting fields Part 7's own field list names that Phase
18's module does not carry as first-class fields: `market_value`, a
resolved `structure` label (LONG_CALL/LONG_PUT/SHORT_CALL/SHORT_PUT/
VERTICAL_SPREAD/UNSUPPORTED_STRUCTURE), per-leg `dte`, `realized_pnl`
(a pass-through the caller supplies -- Phase 18's module has no exit
tracking, and this phase does not add one; Part 15's paper-trading
interfaces are what actually records a realized exit), and Greeks
"where available" -- reconstructed via Phase 26's Black-Scholes solver
(the same `ASSUMED_RISK_FREE_RATE`/`ASSUMED_DIVIDEND_YIELD` used
everywhere else in this codebase) ONLY when a real current mark and a
real underlying price are both supplied, using Phase 18's own
`Greeks`/`GreeksProvenance`/`DerivedGreeksMetadata` schema
(`DERIVED_FROM_MODEL`, never faked as `OBSERVED_FROM_SOURCE`). When
either input is missing, `Greeks.unavailable()` -- never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.options.black_scholes import BlackScholesInputs, black_scholes_greeks, implied_volatility_bisection
from src.options.greeks import DerivedGreeksMetadata, Greeks, GreeksProvenance
from src.options.phase26_iv_greeks_certification import ASSUMED_DIVIDEND_YIELD, ASSUMED_RISK_FREE_RATE, PRICING_MODEL
from src.options.position import OptionLegPosition, OptionsPosition, analyze_position_risk

GREEKS_RECONSTRUCTION_VERSION = "phase30_research_position_view_v1"


@dataclass(frozen=True)
class LegSnapshot:
    contract_id: str
    underlying: str
    call_put: str
    strike: float
    expiration: date
    side: str  # "long" | "short"
    quantity: int
    entry_price: float
    current_mark: float | None
    dte: int | None
    greeks: Greeks


@dataclass(frozen=True)
class PositionSnapshot:
    structure: str  # "LONG_CALL" | "LONG_PUT" | "SHORT_CALL" | "SHORT_PUT" | "VERTICAL_SPREAD" | "UNSUPPORTED_STRUCTURE"
    strategy_label: str | None
    legs: tuple[LegSnapshot, ...]
    opened_at: datetime
    as_of: datetime
    market_value: float | None  # None if any leg's current mark is missing -- never partially computed
    unrealized_pnl: float | None
    realized_pnl: float  # 0.0 until the caller supplies a real recorded exit amount
    max_loss: float | None
    max_gain: float | None
    is_defined_risk: bool
    risk_method: str


def classify_structure(position: OptionsPosition) -> str:
    if position.is_single_leg:
        leg = position.legs[0]
        return f"{leg.side.upper()}_{leg.contract.call_put.upper()}"
    if len(position.legs) == 2:
        risk = analyze_position_risk(position)
        if "vertical spread" in risk.method:
            return "VERTICAL_SPREAD"
    return "UNSUPPORTED_STRUCTURE"


def _reconstruct_leg_greeks(
    leg: OptionLegPosition, *, current_mark: float | None, underlying_price: float | None, as_of: datetime,
    risk_free_rate: float, dividend_yield: float,
) -> Greeks:
    if current_mark is None or underlying_price is None or current_mark <= 0 or underlying_price <= 0:
        return Greeks.unavailable()
    t_years = (leg.contract.expiration - as_of.date()).days / 365.0
    if t_years <= 0:
        return Greeks.unavailable()

    iv = implied_volatility_bisection(
        target_price=current_mark, underlying_price=underlying_price, strike=leg.contract.strike,
        time_to_expiration_years=t_years, risk_free_rate=risk_free_rate, dividend_yield=dividend_yield,
        call_put=leg.contract.call_put,
    )
    if iv is None:
        return Greeks.unavailable()

    inputs = BlackScholesInputs(underlying_price, leg.contract.strike, t_years, risk_free_rate, iv, dividend_yield)
    g = black_scholes_greeks(inputs, call_put=leg.contract.call_put)
    metadata = DerivedGreeksMetadata(
        model=PRICING_MODEL,
        inputs={"underlying_price": underlying_price, "strike": leg.contract.strike, "time_to_expiration_years": t_years},
        timestamp=as_of, volatility_input=iv, rate_assumption=risk_free_rate,
        dividend_assumption=dividend_yield, version=GREEKS_RECONSTRUCTION_VERSION,
    )
    return Greeks(delta=g.delta, gamma=g.gamma, theta=g.theta, vega=g.vega, rho=g.rho,
                   provenance=GreeksProvenance.DERIVED_FROM_MODEL, derived_metadata=metadata)


def build_position_snapshot(
    position: OptionsPosition, *,
    current_marks: dict[str, float],
    as_of: datetime,
    underlying_prices: dict[str, float] | None = None,
    realized_pnl: float = 0.0,
    risk_free_rate: float = ASSUMED_RISK_FREE_RATE,
    dividend_yield: float = ASSUMED_DIVIDEND_YIELD,
) -> PositionSnapshot:
    """`current_marks` keyed by option_id (Phase 18's own convention);
    `underlying_prices` keyed by underlying symbol -- both optional per
    leg; anything missing degrades that leg's market_value/Greeks to
    None/UNAVAILABLE rather than guessing."""
    underlying_prices = underlying_prices or {}
    risk = analyze_position_risk(position)
    structure = classify_structure(position)

    legs = []
    for leg in position.legs:
        mark = current_marks.get(leg.contract.option_id)
        dte = (leg.contract.expiration - as_of.date()).days
        greeks = _reconstruct_leg_greeks(
            leg, current_mark=mark, underlying_price=underlying_prices.get(leg.contract.underlying_symbol),
            as_of=as_of, risk_free_rate=risk_free_rate, dividend_yield=dividend_yield,
        )
        legs.append(LegSnapshot(
            contract_id=leg.contract.option_id, underlying=leg.contract.underlying_symbol,
            call_put=leg.contract.call_put, strike=leg.contract.strike, expiration=leg.contract.expiration,
            side=leg.side, quantity=leg.quantity, entry_price=leg.entry_price, current_mark=mark, dte=dte,
            greeks=greeks,
        ))

    market_value = None
    if all(current_marks.get(leg.contract.option_id) is not None for leg in position.legs):
        market_value = sum(
            current_marks[leg.contract.option_id] * leg.quantity * leg.contract.contract_multiplier
            * (1 if leg.side == "long" else -1)
            for leg in position.legs
        )

    return PositionSnapshot(
        structure=structure, strategy_label=position.strategy_label, legs=tuple(legs),
        opened_at=position.opened_at, as_of=as_of, market_value=market_value,
        unrealized_pnl=position.unrealized_pnl(current_marks), realized_pnl=realized_pnl,
        max_loss=risk.max_loss, max_gain=risk.max_profit, is_defined_risk=risk.is_defined_risk,
        risk_method=risk.method,
    )
