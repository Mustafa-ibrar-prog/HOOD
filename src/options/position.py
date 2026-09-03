"""Phase 18, Part 11 — the canonical (research/backtest-layer) options
position model.

Distinct from src.position_manager.models.OpenPosition, which is the
LIVE-trading, single-leg-only (long_call/long_put) position record this
codebase's orchestrator/monitor already use for real paper/live
positions -- that model is unchanged by this phase. OptionsPosition here
is the research-layer generalization Part 11 asks for: multi-leg,
research/backtest-oriented, with an explicit "we don't know the max
loss/profit for this structure" escape hatch rather than assuming linear
payoff for everything.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.options.instrument import OptionContract


@dataclass(frozen=True)
class OptionLegPosition:
    contract: OptionContract
    side: str  # "long" | "short"
    quantity: int  # contracts, always positive; side carries the direction
    entry_price: float  # premium per contract at entry
    entry_timestamp: datetime

    def __post_init__(self) -> None:
        if self.side not in ("long", "short"):
            raise ValueError(f"side must be 'long' or 'short', got {self.side!r}")
        if self.quantity <= 0:
            raise ValueError(f"quantity must be > 0, got {self.quantity}")
        if self.entry_price < 0:
            raise ValueError(f"entry_price must be >= 0, got {self.entry_price}")

    @property
    def entry_cashflow(self) -> float:
        """Positive = credit received (short), negative = debit paid
        (long) -- premium * quantity * multiplier."""
        notional = self.entry_price * self.quantity * self.contract.contract_multiplier
        return notional if self.side == "short" else -notional

    def unrealized_pnl(self, current_mark: float) -> float:
        notional = (current_mark - self.entry_price) * self.quantity * self.contract.contract_multiplier
        return notional if self.side == "long" else -notional


@dataclass(frozen=True)
class OptionsPosition:
    """A one-or-more-leg options position. `strategy_label` is
    descriptive metadata only (e.g. "bull_call_spread") -- it does NOT
    drive risk-profile logic; analyze_position_risk (below) determines
    the actual structure from the legs themselves, never trusts the
    label."""

    legs: tuple[OptionLegPosition, ...]
    opened_at: datetime
    strategy_label: str | None = None

    def __post_init__(self) -> None:
        if not self.legs:
            raise ValueError("OptionsPosition must have at least one leg")

    @property
    def is_single_leg(self) -> bool:
        return len(self.legs) == 1

    @property
    def net_entry_cashflow(self) -> float:
        """Positive = net credit, negative = net debit."""
        return sum(leg.entry_cashflow for leg in self.legs)

    def unrealized_pnl(self, current_marks: dict[str, float]) -> float | None:
        """`current_marks` keyed by option_id. Returns None (never a
        partial/wrong number) if any leg's mark is missing."""
        total = 0.0
        for leg in self.legs:
            mark = current_marks.get(leg.contract.option_id)
            if mark is None:
                return None
            total += leg.unrealized_pnl(mark)
        return total

    @property
    def underlying_symbols(self) -> tuple[str, ...]:
        return tuple(sorted({leg.contract.underlying_symbol for leg in self.legs}))


@dataclass(frozen=True)
class PositionRiskProfile:
    max_loss: float | None  # None = not determinable by this implementation (never a guess)
    max_profit: float | None
    is_defined_risk: bool
    method: str  # explains HOW determined, or why not


def analyze_position_risk(position: OptionsPosition) -> PositionRiskProfile:
    """Part 11: 'Do not assume all option structures have simple linear
    P&L.' Correctly handles: single-leg long/short call/put, and 2-leg
    same-expiration same-call_put vertical spreads (one long, one short).
    Everything else returns (None, None) with an explicit reason --
    never a wrong number for a structure this function doesn't actually
    understand."""
    if position.is_single_leg:
        return _single_leg_risk(position.legs[0])
    if len(position.legs) == 2:
        vertical = _vertical_spread_risk(position.legs[0], position.legs[1])
        if vertical is not None:
            return vertical
    return PositionRiskProfile(
        max_loss=None, max_profit=None, is_defined_risk=False,
        method=f"UNSUPPORTED_STRUCTURE: max loss/profit not implemented for {len(position.legs)}-leg combination "
               f"{[(leg.side, leg.contract.call_put) for leg in position.legs]} -- do not assume simple linear payoff",
    )


def _single_leg_risk(leg: OptionLegPosition) -> PositionRiskProfile:
    premium_notional = leg.entry_price * leg.quantity * leg.contract.contract_multiplier
    strike_notional = leg.contract.strike * leg.quantity * leg.contract.contract_multiplier

    if leg.side == "long" and leg.contract.call_put == "call":
        return PositionRiskProfile(max_loss=premium_notional, max_profit=None, is_defined_risk=True, method="long call: max_loss=premium paid; max_profit=unbounded (upside uncapped)")
    if leg.side == "long" and leg.contract.call_put == "put":
        return PositionRiskProfile(max_loss=premium_notional, max_profit=strike_notional - premium_notional, is_defined_risk=True, method="long put: max_loss=premium paid; max_profit=strike*mult-premium (underlying floors at 0)")
    if leg.side == "short" and leg.contract.call_put == "call":
        return PositionRiskProfile(max_loss=None, max_profit=premium_notional, is_defined_risk=False, method="short (naked) call: max_profit=premium received; max_loss=unbounded (upside uncapped)")
    if leg.side == "short" and leg.contract.call_put == "put":
        return PositionRiskProfile(max_loss=strike_notional - premium_notional, max_profit=premium_notional, is_defined_risk=True, method="short (cash-secured) put: max_loss=strike*mult-premium (underlying floors at 0); max_profit=premium received")
    raise AssertionError("unreachable: side/call_put already validated by OptionLegPosition.__post_init__")


def _vertical_spread_risk(leg_a: OptionLegPosition, leg_b: OptionLegPosition) -> PositionRiskProfile | None:
    """Only handles a genuine same-expiration, same-call_put, opposite-
    side, equal-quantity vertical spread. Returns None (not a
    PositionRiskProfile) for anything else, so the caller falls through
    to the UNSUPPORTED_STRUCTURE default rather than misclassifying."""
    if leg_a.contract.expiration != leg_b.contract.expiration:
        return None
    if leg_a.contract.call_put != leg_b.contract.call_put:
        return None
    if leg_a.side == leg_b.side:
        return None
    if leg_a.quantity != leg_b.quantity:
        return None
    if leg_a.contract.underlying_symbol != leg_b.contract.underlying_symbol:
        return None

    long_leg = leg_a if leg_a.side == "long" else leg_b
    short_leg = leg_b if leg_a.side == "long" else leg_a
    width = abs(long_leg.contract.strike - short_leg.contract.strike) * long_leg.quantity * long_leg.contract.contract_multiplier
    net_debit_credit = -(long_leg.entry_cashflow + short_leg.entry_cashflow)  # positive = net debit paid, negative = net credit received

    if net_debit_credit >= 0:
        # Net debit paid: max_loss = debit paid; max_profit = width - debit paid.
        return PositionRiskProfile(
            max_loss=net_debit_credit, max_profit=width - net_debit_credit, is_defined_risk=True,
            method=f"{long_leg.contract.call_put} vertical spread, net debit={net_debit_credit:.2f}: max_loss=debit paid; max_profit=strike_width-debit",
        )
    net_credit = -net_debit_credit
    return PositionRiskProfile(
        max_loss=width - net_credit, max_profit=net_credit, is_defined_risk=True,
        method=f"{long_leg.contract.call_put} vertical spread, net credit={net_credit:.2f}: max_profit=credit received; max_loss=strike_width-credit",
    )
