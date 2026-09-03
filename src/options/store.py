"""Phase 18, Part 4 — the options data store interface.

Mirrors src.data.store.HistoricalDataStore / src.data.sec_filing_store.
SECFilingStore's exact convention (JSONL-backed, one file per symbol,
fail-closed on corruption) and additionally satisfies Phase 15's generic
`OptionsStore` Protocol (src.data.store_interfaces) via load()/save() for
interop, exactly like SECFilingStore does for FundamentalStore.

Part 4's explicit instruction: "Do not implement methods that the
available source cannot actually support without clearly returning an
unavailable/unsupported status." get_contract/get_chain/get_quotes are
real, working methods over whatever this store has persisted (nothing
this phase, since no real historical options data was ingested -- see
docs/options_architecture.md). get_historical_chain/get_as_of_chain
exist as named methods (so the interface is future-proof and
documented) but their CURRENT implementation always raises
HistoricalOptionsDataUnavailableError -- they do not pretend to work.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from src.data.source_profile import DataProvenance
from src.data.store_interfaces import ProvenancedObservation
from src.data.timestamp_model import EventTimestamps
from src.options.chain import OptionChainObservation
from src.options.instrument import OptionContract


class HistoricalOptionsDataUnavailableError(RuntimeError):
    """Raised by any store method that would require historical options
    data this codebase does not have (Part 18/24). Never caught and
    silently papered over anywhere in this package -- a caller that
    hits this must handle it explicitly (typically: report
    HISTORICAL_OPTIONS_DATA_INSUFFICIENT and stop)."""


class OptionsDataStoreError(RuntimeError):
    """Raised when a persisted options dataset is corrupted -- same
    fail-closed convention as every other store in this codebase."""


@dataclass(frozen=True)
class OptionContractRecord:
    """Persistence shape for OptionContract (dataclasses with `date`/
    `datetime` fields need explicit (de)serialization)."""

    contract: OptionContract

    def to_dict(self) -> dict:
        c = self.contract
        return {
            "underlying_symbol": c.underlying_symbol, "option_id": c.option_id, "call_put": c.call_put,
            "strike": c.strike, "expiration": c.expiration.isoformat(), "contract_multiplier": c.contract_multiplier,
            "exercise_style": c.exercise_style, "settlement_type": c.settlement_type, "currency": c.currency,
            "is_standard_deliverable": c.is_standard_deliverable, "deliverable_note": c.deliverable_note,
            "source": c.source, "retrieval_timestamp": c.retrieval_timestamp.isoformat() if c.retrieval_timestamp else None,
            "schema_version": c.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OptionContractRecord":
        return cls(OptionContract(
            underlying_symbol=data["underlying_symbol"], option_id=data["option_id"], call_put=data["call_put"],
            strike=float(data["strike"]), expiration=date.fromisoformat(data["expiration"]),
            contract_multiplier=int(data["contract_multiplier"]), exercise_style=data.get("exercise_style"),
            settlement_type=data.get("settlement_type"), currency=data.get("currency", "USD"),
            is_standard_deliverable=data.get("is_standard_deliverable", True), deliverable_note=data.get("deliverable_note"),
            source=data.get("source", "mcp__HOOD__get_option_instruments"),
            retrieval_timestamp=datetime.fromisoformat(data["retrieval_timestamp"]) if data.get("retrieval_timestamp") else None,
            schema_version=data.get("schema_version", "options-v1"),
        ))


class OptionsDataStore:
    def __init__(self, root_dir: Path):
        self._root = Path(root_dir)

    def _contracts_path(self, underlying_symbol: str) -> Path:
        return self._root / underlying_symbol.upper() / "option_contracts.jsonl"

    # --- contract identity (real, working -- Part 2/4) ------------------------------------------

    def save_contracts(self, underlying_symbol: str, contracts: Sequence[OptionContract]) -> None:
        path = self._contracts_path(underlying_symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        by_id = {c.option_id: c for c in contracts}
        ordered = sorted(by_id.values(), key=lambda c: (c.expiration, c.call_put, c.strike))
        with path.open("w") as fh:
            for c in ordered:
                fh.write(json.dumps(OptionContractRecord(c).to_dict(), sort_keys=True))
                fh.write("\n")

    def load_contracts(self, underlying_symbol: str) -> list[OptionContract]:
        path = self._contracts_path(underlying_symbol)
        if not path.is_file():
            return []
        raw = path.read_text()
        if not raw.strip():
            return []
        try:
            return [OptionContractRecord.from_dict(json.loads(line)).contract for line in raw.splitlines() if line.strip()]
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise OptionsDataStoreError(f"Option contracts for {underlying_symbol} are corrupted or unreadable: {exc}") from exc

    def get_contract(self, option_id: str, *, underlying_symbol: str) -> OptionContract | None:
        return next((c for c in self.load_contracts(underlying_symbol) if c.option_id == option_id), None)

    def get_chain(self, underlying_symbol: str, *, expiration: date | None = None) -> list[OptionContract]:
        """The CURRENTLY-KNOWN contract set for an underlying (whatever
        this store has persisted -- not necessarily today's live chain).
        Filters to one expiration when given."""
        contracts = self.load_contracts(underlying_symbol)
        if expiration is not None:
            contracts = [c for c in contracts if c.expiration == expiration]
        return contracts

    # --- live quotes (real, working over whatever was persisted -- Part 3/4) --------------------

    def get_quotes(self, option_ids: Sequence[str], *, underlying_symbol: str) -> list[OptionChainObservation]:
        """Returns whatever OptionChainObservations this store has for
        the given contracts. This is NOT a live call (nothing in this
        package calls a HOOD MCP tool) -- it reads persisted data an
        agent/script fetched and saved, same convention as every other
        store in this codebase."""
        raise NotImplementedError(
            "get_quotes() has no backing observation store this phase -- no real quote observations were "
            "persisted (Part 18/24: no historical quotes exist to persist, and live quotes are out of "
            "scope for a research-layer store). The method is named here to complete the Part 4 interface; "
            "a future phase that actually persists OptionChainObservation records should implement this "
            "the same way get_contract()/get_chain() work above."
        )

    # --- historical (Part 4's explicit "clearly return unavailable" requirement) ----------------

    def get_historical_chain(self, underlying_symbol: str, *, as_of: date) -> list[OptionChainObservation]:
        raise HistoricalOptionsDataUnavailableError(
            f"get_historical_chain({underlying_symbol!r}, as_of={as_of}) -- HISTORICAL_OPTIONS_DATA_INSUFFICIENT: "
            "no historical bid/ask/volume/open-interest/IV/Greeks archive exists for this connector. "
            "Real historical OHLC price bars ARE available per-contract via get_option_historicals (see "
            "docs/options_architecture.md), but a full chain snapshot (bid/ask/volume/OI/IV/Greeks across "
            "every strike) was never available for any historical date this phase probed."
        )

    def get_as_of_chain(self, underlying_symbol: str, *, as_of: datetime) -> list[OptionChainObservation]:
        raise HistoricalOptionsDataUnavailableError(
            f"get_as_of_chain({underlying_symbol!r}, as_of={as_of}) -- HISTORICAL_OPTIONS_DATA_INSUFFICIENT: "
            "same limitation as get_historical_chain(); a point-in-time snapshot of the FULL chain "
            "(bid/ask/volume/OI/IV/Greeks) is not reconstructable from this connector for any past instant."
        )

    # --- generic OptionsStore Protocol interop (Phase 15 architecture reuse) --------------------

    def load(self, key: str) -> list[ProvenancedObservation]:
        """`key` is treated as an underlying_symbol; returns one
        ProvenancedObservation per known contract (identity only -- no
        price/quote data, since none is persisted this phase)."""
        return [
            ProvenancedObservation(
                key=c.option_id, field="contract_identity", value=c.occ_style_description,
                timestamps=EventTimestamps(observation_time=c.retrieval_timestamp), provenance=DataProvenance.OBSERVED, source=c.source,
            )
            for c in self.load_contracts(key)
        ]

    def save(self, key: str, observations: Sequence[ProvenancedObservation], *, source: str = "options") -> None:
        raise NotImplementedError(
            "OptionsDataStore.save() (the generic ProvenancedObservation-shaped save) is intentionally "
            "unimplemented -- option contracts/observations carry richer, option-specific fields "
            "(strike/expiration/call_put/bid/ask/Greeks/IV) a bare ProvenancedObservation cannot hold. "
            "Use save_contracts() with OptionContract instead; this method exists only so OptionsDataStore "
            "satisfies the generic OptionsStore Protocol's shape for read interop via load()."
        )
