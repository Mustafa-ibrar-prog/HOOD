"""Phase 38, Part 1-2 — the causal strategy-validation dataset layer,
built directly from Phase 37's real, recorded observations (never a
new market-data provider, never a new tool call).

Part 1's audit finding, verified directly against the repository at the
start of this phase (no Settings field or scheduled job invokes
`src.research_recorder.recorder.run_observation_cycle` anywhere in
this codebase; `logs/` contains no `research_recorder`-shaped store
file): **zero real live observation cycles have been recorded.**
Phase 37 built and tested the recorder; nothing has run it against the
real Robinhood integration yet. Every function below is written to
operate correctly on whatever real data exists -- today that is zero
rows -- and every downstream module (targets, falsification, economic
validation, the gate) must degrade to an honest "insufficient sample"
answer rather than fabricate one.

`CausalFeatureRow` reuses Phase 37's own normalized-observation schema
field-for-field (`src.research_recorder.normalized_observation`) --
this module does not invent a new option/underlying shape, it joins the
underlying and option rows for one (observation_cycle_id, option_id)
pair and attaches a raw-payload reference. Reads Phase 37's stores
directly (`RawObservationStore`/`NormalizedUnderlyingStore`/
`NormalizedOptionStore`), never re-fetches anything live.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from src.research_recorder.storage import NormalizedOptionStore, NormalizedUnderlyingStore, RawObservationStore


@dataclass(frozen=True)
class CausalFeatureRow:
    """Everything known about one option contract at one observation
    cycle -- exactly the fields Part 2 lists, no more, no less. Never
    contains any field from a LATER cycle; see `phase38_targets.py` for
    the strictly-separate forward-looking target construction."""

    observation_cycle_id: str
    observation_timestamp: datetime
    underlying_symbol: str
    option_id: str
    option_type: str | None
    strike: float | None
    expiration: date | None
    dte: int | None
    moneyness: float | None

    underlying_last: float | None
    underlying_bid: float | None
    underlying_ask: float | None
    underlying_midpoint: float | None

    option_bid: float | None
    option_ask: float | None
    option_bid_size: int | None
    option_ask_size: int | None
    option_mark: float | None
    option_midpoint: float | None
    implied_volatility: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    rho: float | None
    open_interest: int | None
    volume: int | None
    contract_state: str | None
    contract_tradability: str | None

    field_provenance: Mapping[str, str]
    raw_payload_fingerprint: str | None  # a reference into RawObservationStore -- never the payload itself, duplicated


def _option_midpoint(row: Mapping[str, Any]) -> float | None:
    bid, ask = row.get("bid"), row.get("ask")
    return (bid + ask) / 2 if bid is not None and ask is not None else None


def build_causal_feature_row(
    option_row: Mapping[str, Any],
    *,
    underlying_row: Mapping[str, Any] | None,
    raw_payload_fingerprint: str | None,
) -> CausalFeatureRow:
    """Pure function of ONE option observation row (plus its same-cycle
    underlying row) -- structurally incapable of seeing a later cycle's
    data, since no such data is ever passed in."""
    return CausalFeatureRow(
        observation_cycle_id=option_row["observation_cycle_id"],
        observation_timestamp=datetime.fromisoformat(option_row["observation_timestamp"]),
        underlying_symbol=option_row["underlying"],
        option_id=option_row["option_id"],
        option_type=option_row.get("option_type"),
        strike=option_row.get("strike"),
        expiration=date.fromisoformat(option_row["expiration"]) if option_row.get("expiration") else None,
        dte=option_row.get("dte"),
        moneyness=option_row.get("moneyness"),
        underlying_last=underlying_row.get("last") if underlying_row else None,
        underlying_bid=underlying_row.get("bid") if underlying_row else None,
        underlying_ask=underlying_row.get("ask") if underlying_row else None,
        underlying_midpoint=underlying_row.get("midpoint") if underlying_row else None,
        option_bid=option_row.get("bid"),
        option_ask=option_row.get("ask"),
        option_bid_size=option_row.get("bid_size"),
        option_ask_size=option_row.get("ask_size"),
        option_mark=option_row.get("mark"),
        option_midpoint=_option_midpoint(option_row),
        implied_volatility=option_row.get("implied_volatility"),
        delta=option_row.get("delta"), gamma=option_row.get("gamma"), theta=option_row.get("theta"),
        vega=option_row.get("vega"), rho=option_row.get("rho"),
        open_interest=option_row.get("open_interest"), volume=option_row.get("volume"),
        contract_state=option_row.get("contract_state"), contract_tradability=option_row.get("contract_tradability"),
        field_provenance=option_row.get("field_provenance", {}),
        raw_payload_fingerprint=raw_payload_fingerprint,
    )


def _fingerprint_for(option_row: Mapping[str, Any], raw_observations: list) -> str | None:
    """Finds the RawObservation this option row's real quote data came
    from -- matched by (cycle_id, tool_name='get_option_quotes',
    option_id present in the request context), never a first-match
    fallback across a different cycle."""
    cycle_id = option_row["observation_cycle_id"]
    option_id = option_row["option_id"]
    for obs in raw_observations:
        if obs.observation_cycle_id != cycle_id or obs.tool_name != "get_option_quotes":
            continue
        if option_id in (obs.request_context.get("option_ids") or []):
            return obs.payload_fingerprint
    return None


def build_causal_validation_dataset(
    *,
    raw_store: "RawObservationStore",
    underlying_store: "NormalizedUnderlyingStore",
    option_store: "NormalizedOptionStore",
) -> list[CausalFeatureRow]:
    """The single, real entry point -- reads only from Phase 37's own
    stores. Returns an empty list (never a fabricated row) when no
    observations have ever been recorded."""
    option_rows = option_store.load_all_raw_dicts()
    underlying_rows = underlying_store.load_all_raw_dicts()
    raw_observations = raw_store.load_all()

    underlying_by_key = {(r["observation_cycle_id"], r["symbol"]): r for r in underlying_rows}

    dataset = []
    for option_row in option_rows:
        underlying_row = underlying_by_key.get((option_row["observation_cycle_id"], option_row["underlying"]))
        fingerprint = _fingerprint_for(option_row, raw_observations)
        dataset.append(build_causal_feature_row(option_row, underlying_row=underlying_row, raw_payload_fingerprint=fingerprint))
    return dataset
