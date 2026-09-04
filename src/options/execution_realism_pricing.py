"""Phase 30, Part 6/17 — execution realism price abstractions.

The close price is NEVER used as an automatic executable price anywhere
in this module (Part 6's explicit prohibition) -- every function below
starts from a real observed bid and/or ask, or returns
`EXECUTION_DATA_LIMITED` with `execution_price=None`. Nothing here
invents a quote that was not actually observed.
"""

from __future__ import annotations

import dataclasses
import enum
from dataclasses import dataclass
from datetime import datetime

from src.options.research_dataset import ResearchObservation


class ExecutionPriceModel(enum.Enum):
    BUY_AT_ASK = "buy_at_ask"
    SELL_AT_BID = "sell_at_bid"
    BUY_AT_MID = "buy_at_mid"
    SELL_AT_MID = "sell_at_mid"
    DELAYED_EXECUTION = "delayed_execution"
    SLIPPAGE_ASSUMPTION = "slippage_assumption"
    EXECUTION_DATA_LIMITED = "execution_data_limited"  # no real bid/ask exists to price against


@dataclass(frozen=True)
class ExecutionPriceResult:
    option_id: str
    observation_timestamp: datetime
    model: ExecutionPriceModel
    execution_price: float | None
    reference_bid: float | None
    reference_ask: float | None
    slippage_assumption_usd: float | None  # only non-None for SLIPPAGE_ASSUMPTION -- an explicit, labeled assumption, not an observation
    note: str


def _data_limited(row: ResearchObservation, model: ExecutionPriceModel, note: str) -> ExecutionPriceResult:
    return ExecutionPriceResult(
        option_id=row.option_id, observation_timestamp=row.observation_timestamp,
        model=ExecutionPriceModel.EXECUTION_DATA_LIMITED, execution_price=None,
        reference_bid=row.bid, reference_ask=row.ask, slippage_assumption_usd=None, note=note,
    )


def buy_at_ask(row: ResearchObservation) -> ExecutionPriceResult:
    if row.ask is None:
        return _data_limited(row, ExecutionPriceModel.BUY_AT_ASK, "no real ask observed for this contract at this timestamp")
    return ExecutionPriceResult(
        option_id=row.option_id, observation_timestamp=row.observation_timestamp,
        model=ExecutionPriceModel.BUY_AT_ASK, execution_price=row.ask,
        reference_bid=row.bid, reference_ask=row.ask, slippage_assumption_usd=None,
        note="real observed ask",
    )


def sell_at_bid(row: ResearchObservation) -> ExecutionPriceResult:
    if row.bid is None:
        return _data_limited(row, ExecutionPriceModel.SELL_AT_BID, "no real bid observed for this contract at this timestamp")
    return ExecutionPriceResult(
        option_id=row.option_id, observation_timestamp=row.observation_timestamp,
        model=ExecutionPriceModel.SELL_AT_BID, execution_price=row.bid,
        reference_bid=row.bid, reference_ask=row.ask, slippage_assumption_usd=None,
        note="real observed bid",
    )


def _mid(row: ResearchObservation, model: ExecutionPriceModel) -> ExecutionPriceResult:
    if row.bid is None or row.ask is None:
        return _data_limited(row, model, "both a real bid and a real ask are required for a mid-price execution assumption")
    return ExecutionPriceResult(
        option_id=row.option_id, observation_timestamp=row.observation_timestamp,
        model=model, execution_price=(row.bid + row.ask) / 2,
        reference_bid=row.bid, reference_ask=row.ask, slippage_assumption_usd=None,
        note="midpoint of real observed bid/ask",
    )


def buy_at_mid(row: ResearchObservation) -> ExecutionPriceResult:
    return _mid(row, ExecutionPriceModel.BUY_AT_MID)


def sell_at_mid(row: ResearchObservation) -> ExecutionPriceResult:
    return _mid(row, ExecutionPriceModel.SELL_AT_MID)


_BASE_MODEL_FUNCS = {
    ExecutionPriceModel.BUY_AT_ASK: buy_at_ask,
    ExecutionPriceModel.SELL_AT_BID: sell_at_bid,
    ExecutionPriceModel.BUY_AT_MID: buy_at_mid,
    ExecutionPriceModel.SELL_AT_MID: sell_at_mid,
}


def delayed_execution(
    row: ResearchObservation, subsequent_rows: list[ResearchObservation], *,
    delay_count: int, base_model: ExecutionPriceModel = ExecutionPriceModel.BUY_AT_ASK,
) -> ExecutionPriceResult:
    """Simulates "the order didn't fill at this bar's own quote; it filled
    `delay_count` real observations later." `subsequent_rows` must be
    same-contract rows (any order); only entries strictly after `row`'s
    own timestamp are considered, sorted ascending. If fewer than
    `delay_count` real future observations exist, this is
    EXECUTION_DATA_LIMITED -- never approximated from the current row."""
    if delay_count < 1 or base_model not in _BASE_MODEL_FUNCS:
        return _data_limited(row, ExecutionPriceModel.DELAYED_EXECUTION, "invalid delay_count or base_model")
    candidates = sorted(
        (r for r in subsequent_rows if r.option_id == row.option_id and r.observation_timestamp > row.observation_timestamp),
        key=lambda r: r.observation_timestamp,
    )
    if len(candidates) < delay_count:
        return _data_limited(row, ExecutionPriceModel.DELAYED_EXECUTION,
                              f"fewer than {delay_count} real subsequent observation(s) exist for this contract")
    target_row = candidates[delay_count - 1]
    inner = _BASE_MODEL_FUNCS[base_model](target_row)
    return dataclasses.replace(
        inner, model=ExecutionPriceModel.DELAYED_EXECUTION,
        note=f"delayed {delay_count} real observation(s); filled against {base_model.value} at {target_row.observation_timestamp.isoformat()}",
    )


def slippage_assumption(row: ResearchObservation, *, side: str, slippage_usd: float) -> ExecutionPriceResult:
    """An EXPLICIT, labeled assumption layered on top of a real bid/ask --
    `slippage_assumption_usd` is always populated on a successful result
    so a caller can never mistake this for an observed fill price."""
    if side not in ("buy", "sell"):
        raise ValueError("side must be 'buy' or 'sell'")
    base = buy_at_ask(row) if side == "buy" else sell_at_bid(row)
    if base.execution_price is None:
        return base
    adjusted = base.execution_price + slippage_usd if side == "buy" else base.execution_price - slippage_usd
    return dataclasses.replace(
        base, model=ExecutionPriceModel.SLIPPAGE_ASSUMPTION, execution_price=adjusted,
        slippage_assumption_usd=slippage_usd,
        note=f"real {'ask' if side == 'buy' else 'bid'} + an assumed ${slippage_usd:.4f}/share slippage, NOT an observed fill",
    )
