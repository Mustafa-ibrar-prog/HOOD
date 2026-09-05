"""Phase 38, Part 3 — realistic forward option targets, computed ONLY
from information that becomes available AFTER the entry observation.

Strict information timing (Part 2's explicit requirement): every
function here takes an `entry` row and a separate `later_rows` sequence;
`compute_forward_outcome` filters `later_rows` down to strictly
`timestamp > entry.observation_timestamp` before using ANY of them --
verified directly by `tests/test_phase38_no_lookahead.py`. There is no
parameter anywhere in this module through which a future price could
reach a feature -- targets and features are built by entirely separate
functions in separate modules.

Executable-return variants use bid (to sell/close) and ask (to buy/open)
explicitly -- NEVER the midpoint, which is not necessarily fillable
(Part 3: "DO NOT assume that the option mid-price is executable"). When
the data needed for a target is missing, the target is `None` with
`data_limited_reason` set — never fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from src.options.phase38_causal_validation_dataset import CausalFeatureRow

FLAT_BAND_PCT = 0.02  # +/- 2% treated as FLAT for the directional-outcome label -- a disclosed, documented bucket boundary, not a trading threshold


@dataclass(frozen=True)
class ForwardHorizon:
    label: str
    target_minutes: float
    tolerance_minutes: float


# Horizons chosen relative to Phase 37's default 5-minute observation
# cadence (src.research_recorder.recorder.RecorderConfig.observation_interval_minutes)
# -- never assuming a specific historical bar interval, since live
# observations are irregularly spaced in practice (a missed cycle, an
# API failure, market close/reopen).
DEFAULT_HORIZONS: tuple[ForwardHorizon, ...] = (
    ForwardHorizon("5min", 5, 3),
    ForwardHorizon("15min", 15, 7),
    ForwardHorizon("30min", 30, 10),
    ForwardHorizon("1hr", 60, 15),
    ForwardHorizon("eod", 390, 30),  # ~one regular trading session
)


@dataclass(frozen=True)
class ForwardOutcome:
    option_id: str
    underlying_symbol: str
    horizon_label: str
    entry_cycle_id: str
    entry_timestamp: datetime
    exit_cycle_id: str | None
    exit_timestamp: datetime | None

    entry_ask: float | None  # the real cost to buy-to-open
    entry_bid: float | None
    exit_bid: float | None  # the real proceeds from sell-to-close
    exit_ask: float | None

    mid_return_pct: float | None  # entry/exit MIDPOINT return -- diagnostic only, never presented as executable
    executable_return_pct: float | None  # buy at entry ASK, sell at exit BID -- the real, conservative round trip
    mfe_pct: float | None  # best unrealized mid-based excursion vs entry_ask, over the observed path to exit
    mae_pct: float | None  # worst unrealized mid-based excursion vs entry_ask
    directional_outcome: str | None  # "UP" | "DOWN" | "FLAT"
    risk_adjusted_outcome: float | None  # executable_return_pct / abs(mae_pct) when a real adverse excursion was observed

    entry_underlying: float | None
    exit_underlying: float | None
    underlying_return_pct: float | None
    option_minus_underlying_return_pct: float | None  # Phase 32's own established naming for this exact diagnostic

    data_limited_reason: str | None


def _entry_underlying_price(row: CausalFeatureRow) -> float | None:
    return row.underlying_midpoint if row.underlying_midpoint is not None else row.underlying_last


def compute_forward_outcome(
    entry: CausalFeatureRow, later_rows: Sequence[CausalFeatureRow], *, horizon: ForwardHorizon,
) -> ForwardOutcome:
    """`later_rows` may contain rows for ANY option_id/timestamp -- this
    function does the filtering itself (same option_id, strictly later
    timestamp) rather than trusting the caller, so a caller passing in
    an unfiltered dataset can never accidentally leak the wrong
    contract's or an earlier cycle's data into a target."""
    same_contract_later = sorted(
        (r for r in later_rows if r.option_id == entry.option_id and r.observation_timestamp > entry.observation_timestamp),
        key=lambda r: r.observation_timestamp,
    )

    def _unavailable(reason: str) -> ForwardOutcome:
        return ForwardOutcome(
            option_id=entry.option_id, underlying_symbol=entry.underlying_symbol, horizon_label=horizon.label,
            entry_cycle_id=entry.observation_cycle_id, entry_timestamp=entry.observation_timestamp,
            exit_cycle_id=None, exit_timestamp=None, entry_ask=entry.option_ask, entry_bid=entry.option_bid,
            exit_bid=None, exit_ask=None, mid_return_pct=None, executable_return_pct=None, mfe_pct=None, mae_pct=None,
            directional_outcome=None, risk_adjusted_outcome=None, entry_underlying=_entry_underlying_price(entry),
            exit_underlying=None, underlying_return_pct=None, option_minus_underlying_return_pct=None,
            data_limited_reason=reason,
        )

    if not same_contract_later:
        return _unavailable(f"No observation of {entry.option_id} exists after the entry timestamp")
    if entry.option_ask is None or entry.option_bid is None:
        return _unavailable("Entry bid/ask unavailable -- cannot define an executable entry cost")

    # Nearest-to-target-duration match within tolerance, matching Phase
    # 35's tolerance-matching convention for irregularly-sampled real data.
    best = min(
        same_contract_later,
        key=lambda r: abs((r.observation_timestamp - entry.observation_timestamp).total_seconds() / 60 - horizon.target_minutes),
    )
    elapsed_minutes = (best.observation_timestamp - entry.observation_timestamp).total_seconds() / 60
    if abs(elapsed_minutes - horizon.target_minutes) > horizon.tolerance_minutes:
        return _unavailable(f"No observation within {horizon.tolerance_minutes}min of the {horizon.label} target")
    if best.option_bid is None or best.option_ask is None:
        return _unavailable("Exit bid/ask unavailable -- cannot define an executable exit proceeds")

    path = [r for r in same_contract_later if r.observation_timestamp <= best.observation_timestamp]
    mids_on_path = [r.option_midpoint for r in path if r.option_midpoint is not None]

    exit_mid = best.option_midpoint
    entry_ask = entry.option_ask
    mid_return_pct = ((exit_mid - entry.option_midpoint) / entry.option_midpoint) if exit_mid is not None and entry.option_midpoint else None
    executable_return_pct = (best.option_bid - entry_ask) / entry_ask if entry_ask > 0 else None

    mfe_pct = ((max(mids_on_path) - entry_ask) / entry_ask) if mids_on_path and entry_ask > 0 else None
    mae_pct = ((min(mids_on_path) - entry_ask) / entry_ask) if mids_on_path and entry_ask > 0 else None

    if executable_return_pct is None:
        directional_outcome = None
    elif executable_return_pct > FLAT_BAND_PCT:
        directional_outcome = "UP"
    elif executable_return_pct < -FLAT_BAND_PCT:
        directional_outcome = "DOWN"
    else:
        directional_outcome = "FLAT"

    risk_adjusted_outcome = (
        executable_return_pct / abs(mae_pct) if executable_return_pct is not None and mae_pct is not None and mae_pct < 0 else None
    )

    entry_underlying = _entry_underlying_price(entry)
    exit_underlying = _entry_underlying_price(best)
    underlying_return_pct = (
        (exit_underlying - entry_underlying) / entry_underlying if entry_underlying and exit_underlying is not None and entry_underlying > 0 else None
    )
    option_minus_underlying_return_pct = (
        executable_return_pct - underlying_return_pct if executable_return_pct is not None and underlying_return_pct is not None else None
    )

    return ForwardOutcome(
        option_id=entry.option_id, underlying_symbol=entry.underlying_symbol, horizon_label=horizon.label,
        entry_cycle_id=entry.observation_cycle_id, entry_timestamp=entry.observation_timestamp,
        exit_cycle_id=best.observation_cycle_id, exit_timestamp=best.observation_timestamp,
        entry_ask=entry.option_ask, entry_bid=entry.option_bid, exit_bid=best.option_bid, exit_ask=best.option_ask,
        mid_return_pct=mid_return_pct, executable_return_pct=executable_return_pct, mfe_pct=mfe_pct, mae_pct=mae_pct,
        directional_outcome=directional_outcome, risk_adjusted_outcome=risk_adjusted_outcome,
        entry_underlying=entry_underlying, exit_underlying=exit_underlying, underlying_return_pct=underlying_return_pct,
        option_minus_underlying_return_pct=option_minus_underlying_return_pct, data_limited_reason=None,
    )


def compute_forward_outcomes_all_horizons(
    entry: CausalFeatureRow, later_rows: Sequence[CausalFeatureRow], *, horizons: Sequence[ForwardHorizon] = DEFAULT_HORIZONS,
) -> dict[str, ForwardOutcome]:
    return {h.label: compute_forward_outcome(entry, later_rows, horizon=h) for h in horizons}
