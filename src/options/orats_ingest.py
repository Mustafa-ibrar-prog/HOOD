"""Phase 29, Part 3/10 — ORATS ingestion: raw rows -> a normalized
store, a real-data verification record, and raw/normalized-separated
persistence.

Reuses `InMemoryLeanSampleStore` (Phase 26) directly as the generic
options-data container -- despite its Phase-26-era name, every one of
its fields (contracts/lifecycles/quotes/trades/open_interest/underlying)
is provider-agnostic, and every Phase 26/27 quality/PIT/chain/execution
function reads it structurally (duck-typed dict access), never via an
isinstance check -- so reusing the exact class here (rather than
building a parallel one) is genuine reuse, not a misnomer papered over.
A future phase renaming that class to something provider-neutral would
be a reasonable cleanup; this phase does not do that rename (Part 1:
"do not rewrite working components unnecessarily").
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

from src.options.historical_data_interfaces import ContractIdentity, ContractLifecycle
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.orats_schema_mapping import (
    ORATS_SOURCE,
    build_contract_identity_from_strike_row,
    build_orats_provenance,
    map_strike_row_to_observations,
)

DATASET_VERSION = "phase29_orats_v1"


@dataclass(frozen=True)
class RealDataVerificationRecord:
    """Part 3's exact required field list -- one per raw response
    actually retrieved. NEVER constructed for a fabricated/simulated
    response (enforced by this being the only place that builds one,
    and by never calling it from any test that uses a synthetic
    fixture without explicitly labeling `actually_returned_by_provider
    =False`)."""

    provider: str
    product: str
    query: dict
    retrieval_timestamp: datetime
    source_timestamp: str | None
    underlying: str
    contract_count: int
    fields_returned: tuple[str, ...]
    raw_response_fingerprint: str
    actually_returned_by_provider: bool

    def to_json_dict(self) -> dict:
        d = asdict(self)
        d["retrieval_timestamp"] = self.retrieval_timestamp.isoformat()
        return d


def fingerprint_raw_response(raw_rows: list[dict]) -> str:
    """A real, deterministic fingerprint over the EXACT raw response
    bytes (JSON-serialized with sorted keys) -- recomputing it against
    the same raw rows always reproduces the same value."""
    canonical = json.dumps(raw_rows, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_verification_record(
    raw_rows: list[dict], *, product: str, query_params: dict, retrieval_timestamp: datetime,
    underlying: str, actually_returned_by_provider: bool,
) -> RealDataVerificationRecord:
    fields_returned: set[str] = set()
    for row in raw_rows:
        fields_returned.update(row.keys())
    return RealDataVerificationRecord(
        provider="ORATS",
        product=product,
        query=query_params,
        retrieval_timestamp=retrieval_timestamp,
        source_timestamp=raw_rows[0].get("tradeDate") if raw_rows else None,
        underlying=underlying,
        contract_count=len(raw_rows),
        fields_returned=tuple(sorted(fields_returned)),
        raw_response_fingerprint=fingerprint_raw_response(raw_rows),
        actually_returned_by_provider=actually_returned_by_provider,
    )


def ingest_strike_rows(
    raw_rows: list[dict], *, retrieval_timestamp: datetime, today: date,
) -> InMemoryLeanSampleStore:
    """Builds a real, normalized store from real raw ORATS `/strikes`
    rows -- one row covers BOTH the call and put side of one
    ticker/strike/expiration/trade_date, per the real schema. Never
    called on fabricated rows outside a test explicitly labeled
    SYNTHETIC_TEST_DATA."""
    provenance = build_orats_provenance(retrieval_timestamp=retrieval_timestamp)

    contracts: dict[str, ContractIdentity] = {}
    observed_dates: dict[str, list[date]] = defaultdict(list)
    quotes: dict[str, list] = defaultdict(list)
    trades: dict[str, list] = defaultdict(list)
    open_interest: dict[str, list] = defaultdict(list)
    underlying: dict[str, list] = defaultdict(list)

    for row in raw_rows:
        trade_date = datetime.strptime(row["tradeDate"][:10], "%Y-%m-%d")
        for right in ("call", "put"):
            identity = build_contract_identity_from_strike_row(row, right=right, provenance=provenance)
            cid = identity.option_id
            contracts[cid] = identity
            observed_dates[cid].append(trade_date.date())
            q, t, oi, u = map_strike_row_to_observations(
                row, right=right, contract_id=cid, event_time=trade_date, ingestion_time=retrieval_timestamp,
            )
            quotes[cid].extend(q)
            trades[cid].extend(t)
            open_interest[cid].extend(oi)
            if u is not None:
                underlying[row["ticker"]].append(u)

    lifecycles: dict[str, ContractLifecycle] = {}
    for cid, identity in contracts.items():
        from src.options.orats_schema_mapping import build_contract_lifecycle
        lifecycles[cid] = build_contract_lifecycle(cid, identity.expiration, observed_dates[cid], provenance, today=today)

    return InMemoryLeanSampleStore(
        contracts=contracts, lifecycles=lifecycles, quotes=dict(quotes), trades=dict(trades),
        open_interest=dict(open_interest), underlying=dict(underlying),
    )


# --- Part 10: raw/normalized separation, persisted separately, deterministically. ---

def write_raw_archive(raw_rows: list[dict], out_path: Path) -> str:
    """Immutable -- always writes a NEW file (never appends/overwrites
    an existing one silently); returns the real fingerprint of what was
    written."""
    out_path = Path(out_path)
    if out_path.exists():
        raise FileExistsError(f"{out_path} already exists -- raw archives are immutable, never overwritten")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(raw_rows, sort_keys=True, default=str, indent=2))
    return fingerprint_raw_response(raw_rows)


def write_normalized_dataset(store: InMemoryLeanSampleStore, out_path: Path, *, source_fingerprint: str) -> dict:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "_manifest": True, "dataset_version": DATASET_VERSION,
        "source_fingerprint": source_fingerprint, "n_contracts": len(store.contracts),
        "provider": ORATS_SOURCE,
    }
    with out_path.open("w") as f:
        f.write(json.dumps(manifest) + "\n")
        for cid in sorted(store.contracts):
            contract = store.contracts[cid]
            lifecycle = store.lifecycles.get(cid)
            record = {
                "option_id": contract.option_id, "underlying_symbol": contract.underlying_symbol,
                "call_put": contract.call_put, "strike": contract.strike, "expiration": contract.expiration.isoformat(),
                "multiplier": contract.multiplier, "multiplier_source_confirmed": False,
                "exercise_style": contract.exercise_style, "contract_status": contract.contract_status,
                "lifecycle": None if lifecycle is None else {
                    "first_observable_date": lifecycle.first_observable_date.isoformat() if lifecycle.first_observable_date else None,
                    "first_listed_date": lifecycle.first_listed_date.isoformat() if lifecycle.first_listed_date else None,
                    "last_trade_date": lifecycle.last_trade_date.isoformat() if lifecycle.last_trade_date else None,
                    "status": lifecycle.status.value,
                },
                "n_quote_observations": len(store.quotes.get(cid, [])),
                "provenance_source": contract.provenance.source,
            }
            f.write(json.dumps(record) + "\n")
    return manifest
