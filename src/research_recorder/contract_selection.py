"""Phase 37, Part 11-12 — deterministic, documented observation-universe
selection.

Purpose: collect a representative RESEARCH cross-section, never filter
for tradeability. `ContractSelectionBounds` are broad, disclosed,
CONFIGURABLE observation bounds — explicitly NOT final trading
thresholds (Part 11: "DO NOT invent final trading thresholds"). Every
selection decision uses only the chain-candidate row (strike,
expiration, type, state, tradability) and the SAME-CYCLE underlying
price already fetched this cycle — never a later price, never a future
contract's realized outcome (Part 12: "Do not use future information to
select contracts").

Selection rule (documented here, exactly, per Part 11's "document
exactly how contracts are selected"): candidates are bucketed into 3
DTE bands x 3 moneyness bands (see `DteBucket`/`MoneynessBucket`
below); for each of the resulting (up to) 9 buckets, the single
candidate whose (dte, moneyness) is CLOSEST to that bucket's target
point is kept — a deterministic nearest-neighbor pick, never a random
sample, never "first N contracts returned." This directly satisfies
Part 12's "capture near ATM / modestly ITM / modestly OTM x short /
medium / long DTE" requirement without observing the whole chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Mapping, Sequence

from src.research_recorder.dte import compute_dte
from src.research_recorder.moneyness import compute_moneyness


@dataclass(frozen=True)
class ContractSelectionBounds:
    min_dte: int = 1
    max_dte: int = 90
    moneyness_band: float = 0.20  # +/- 20% from the underlying price -- a broad OBSERVATION bound, not a trading filter
    max_contracts_per_symbol_per_cycle: int = 18  # up to 9 buckets x {call, put}


class DteBucket(str, Enum):
    SHORT = "SHORT"  # min_dte..15
    MEDIUM = "MEDIUM"  # 16..45
    LONG = "LONG"  # 46..max_dte


class MoneynessBucket(str, Enum):
    MODEST_ITM = "MODEST_ITM"  # 0.03 < moneyness <= moneyness_band
    NEAR_ATM = "NEAR_ATM"  # -0.03 <= moneyness <= 0.03
    MODEST_OTM = "MODEST_OTM"  # -moneyness_band <= moneyness < -0.03


_DTE_TARGETS = {DteBucket.SHORT: 8, DteBucket.MEDIUM: 30, DteBucket.LONG: 60}
_MONEYNESS_TARGETS = {MoneynessBucket.MODEST_ITM: 0.10, MoneynessBucket.NEAR_ATM: 0.0, MoneynessBucket.MODEST_OTM: -0.10}


def _dte_bucket(dte: int, bounds: ContractSelectionBounds) -> DteBucket | None:
    if dte < bounds.min_dte or dte > bounds.max_dte:
        return None
    if dte <= 15:
        return DteBucket.SHORT
    if dte <= 45:
        return DteBucket.MEDIUM
    return DteBucket.LONG


def _moneyness_bucket(moneyness: float, bounds: ContractSelectionBounds) -> MoneynessBucket | None:
    if moneyness < -bounds.moneyness_band or moneyness > bounds.moneyness_band:
        return None
    if -0.03 <= moneyness <= 0.03:
        return MoneynessBucket.NEAR_ATM
    if moneyness > 0.03:
        return MoneynessBucket.MODEST_ITM
    return MoneynessBucket.MODEST_OTM


@dataclass(frozen=True)
class SelectedContract:
    chain_row: Mapping[str, Any]
    option_type: str
    dte: int
    moneyness: float
    dte_bucket: DteBucket
    moneyness_bucket: MoneynessBucket


def select_observation_contracts(
    chain_candidates: Sequence[Mapping[str, Any]],
    *,
    underlying_price: float,
    now: datetime,
    market_timezone: str,
    bounds: ContractSelectionBounds = ContractSelectionBounds(),
) -> list[SelectedContract]:
    """Deterministic, documented, broad -- see module docstring. Returns
    at most one contract per (option_type, dte_bucket, moneyness_bucket)
    combination, chosen by nearest-to-target distance."""
    best: dict[tuple[str, DteBucket, MoneynessBucket], tuple[float, SelectedContract]] = {}

    for row in chain_candidates:
        option_type = row.get("type") or row.get("option_type")
        if option_type not in ("call", "put"):
            continue
        raw_expiration = row.get("expiration_date") or row.get("expiration")
        strike = row.get("strike_price") or row.get("strike")
        if raw_expiration is None or strike is None:
            continue
        try:
            expiration = date.fromisoformat(str(raw_expiration))
            strike_f = float(strike)
        except (TypeError, ValueError):
            continue

        dte = compute_dte(expiration=expiration, observation_timestamp=now, market_timezone=market_timezone)
        dte_bucket = _dte_bucket(dte, bounds)
        if dte_bucket is None:
            continue

        moneyness_result = compute_moneyness(underlying_price=underlying_price, strike=strike_f, option_type=option_type)
        if moneyness_result.moneyness is None:
            continue
        moneyness_bucket = _moneyness_bucket(moneyness_result.moneyness, bounds)
        if moneyness_bucket is None:
            continue

        distance = abs(dte - _DTE_TARGETS[dte_bucket]) + abs(moneyness_result.moneyness - _MONEYNESS_TARGETS[moneyness_bucket]) * 100
        key = (option_type, dte_bucket, moneyness_bucket)
        candidate = SelectedContract(row, option_type, dte, moneyness_result.moneyness, dte_bucket, moneyness_bucket)
        if key not in best or distance < best[key][0]:
            best[key] = (distance, candidate)

    selected = [candidate for _, candidate in best.values()]
    return selected[: bounds.max_contracts_per_symbol_per_cycle]
