"""Phase 24, Part 16 — provider-agnostic historical options data
architecture. NO vendor is implemented here (Part 16's explicit
instruction) -- every class below is either a `typing.Protocol`
(structural interface, matching this codebase's existing convention in
`src.data.store_interfaces`) or a plain provenance/identity dataclass.

Reuse, not reinvention: Phase 15 already built the exact generic shape
this phase's QUOTE/TRADE/GREEKS/IV/OPEN-INTEREST stores need
(`ProvenancedObservation` -- a natural key, a field name, a value, and a
provenance label) and an `OptionsStore` Protocol with that shape. The
five field-observation stores below (`HistoricalOptionQuoteStore`,
`HistoricalOptionTradeStore`, `HistoricalOptionGreeksStore`,
`HistoricalOptionIVStore`, `HistoricalOptionOpenInterestStore`) are
structurally IDENTICAL to `src.data.store_interfaces.OptionsStore` --
given Part 16's own explicit names for each field category, not because
the shape needs to differ. `field` distinguishes them at the record
level ("bid"/"ask" for quotes, "delta"/"gamma"/... for Greeks,
"implied_volatility" for IV, "open_interest" for OI, "price"/"size" for
trades).

Contract IDENTITY, CHAIN snapshots, and LIFECYCLE genuinely need a
richer shape than a flat field/value pair (Part 3's own field list), so
`HistoricalOptionContractStore`, `HistoricalOptionChainStore`, and
`ContractLifecycleStore` are new. `OptionDataProvenance` is also new --
Part 3's provenance field list (source / retrieval timestamp /
publication timestamp / historical-vs-live semantics / adjustment
status / interpolation flag / confidence-quality status) is more
detailed than Phase 15's plain `DataProvenance` enum (OBSERVED/DERIVED/
MODELED/ESTIMATED, which `OptionDataProvenance.observation_kind` below
reuses directly rather than re-deriving).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, Sequence, runtime_checkable

from src.data.source_profile import DataProvenance
from src.data.store_interfaces import ProvenancedObservation


class HistoricalOrLive(enum.Enum):
    HISTORICAL = "historical"  # a real observation as of a past point in time
    LIVE = "live"  # a current-instant observation -- NEVER backdated and used as if historical (Part 22)


class ContractLifecycleStatus(enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    DELISTED = "delisted"  # withdrawn/inactive without reaching its expiration date
    UNKNOWN = "unknown"  # the source cannot answer this -- never defaulted to ACTIVE or EXPIRED silently


@dataclass(frozen=True)
class OptionDataProvenance:
    """Part 3's PROVENANCE field list, one record per observation (or
    per batch of observations sharing an origin). `interpolation_flag`
    and `adjustment_status` must be set explicitly by whatever code
    constructs this -- there is no default that quietly claims 'no
    interpolation happened' by omission."""

    source: str  # e.g. "robinhood_mcp", "thetadata", "cboe_datashop" -- a vendor-agnostic label, not a class name
    retrieval_timestamp: datetime  # when THIS CODEBASE fetched/received the observation
    publication_timestamp: datetime | None  # when the SOURCE published/settled the observation, if the source states one
    historical_or_live: HistoricalOrLive
    observation_kind: DataProvenance  # reuses Phase 15's OBSERVED/DERIVED/MODELED/ESTIMATED vocabulary directly
    adjustment_status: str  # e.g. "unadjusted", "split_adjusted", "unknown" -- never silently omitted
    interpolation_flag: bool  # True if any part of this observation was synthesized/gap-filled
    confidence_status: str  # e.g. "verified_real_probe", "vendor_documentation_only", "unverified"


@dataclass(frozen=True)
class ContractIdentity:
    """Part 3's CONTRACT IDENTITY field list."""

    option_id: str
    underlying_symbol: str
    call_put: str  # "call" or "put"
    strike: float
    expiration: date
    multiplier: int
    exercise_style: str | None  # "american"/"european" -- None if the source doesn't state it (never guessed)
    contract_status: str  # source's own state label (e.g. "active"/"expired"/"inactive") -- passed through, not reinterpreted
    provenance: OptionDataProvenance


@dataclass(frozen=True)
class ContractLifecycle:
    """Part 7's point-in-time existence field list. Every date field is
    Optional -- a source that cannot supply first_observable_date must
    leave it None, never approximate it from an OHLC series' first bar
    (Part 7's explicit prohibition: 'Do not assume a historical OHLC
    observation proves the full chain was available at that time')."""

    option_id: str
    first_observable_date: date | None
    first_listed_date: date | None
    last_trade_date: date | None
    expiration_date: date
    status: ContractLifecycleStatus
    provenance: OptionDataProvenance


@runtime_checkable
class HistoricalOptionContractStore(Protocol):
    def get_contract(self, option_id: str) -> ContractIdentity | None: ...

    def list_contracts_for_expiration(self, underlying_symbol: str, expiration: date) -> list[ContractIdentity]: ...

    def save_contracts(self, contracts: Sequence[ContractIdentity]) -> object: ...


@runtime_checkable
class HistoricalOptionChainStore(Protocol):
    """A CHAIN SNAPSHOT is 'every contract believed tradable as of a
    specific timestamp' (Part 11). No currently-audited source (Part 18)
    can populate this with genuine point-in-time fidelity -- this
    Protocol exists so a future source that CAN is a drop-in, not a
    redesign; a caller must check `ContractLifecycle.status` per
    contract rather than assume snapshot completeness."""

    def get_chain_snapshot(self, underlying_symbol: str, as_of: datetime) -> list[ContractIdentity]: ...

    def save_chain_snapshot(self, underlying_symbol: str, as_of: datetime, contracts: Sequence[ContractIdentity]) -> object: ...


@runtime_checkable
class ContractLifecycleStore(Protocol):
    def get_lifecycle(self, option_id: str) -> ContractLifecycle | None: ...

    def save_lifecycle(self, lifecycle: ContractLifecycle) -> object: ...


@runtime_checkable
class HistoricalOptionQuoteStore(Protocol):
    """bid/ask/bid_size/ask_size, field-tagged -- see module docstring."""

    def load(self, contract_id: str) -> list[ProvenancedObservation]: ...

    def save(self, contract_id: str, observations: Sequence[ProvenancedObservation], *, source: str = ...) -> object: ...


@runtime_checkable
class HistoricalOptionTradeStore(Protocol):
    """last trade price/size, field-tagged."""

    def load(self, contract_id: str) -> list[ProvenancedObservation]: ...

    def save(self, contract_id: str, observations: Sequence[ProvenancedObservation], *, source: str = ...) -> object: ...


@runtime_checkable
class HistoricalOptionGreeksStore(Protocol):
    """delta/gamma/theta/vega/rho, field-tagged."""

    def load(self, contract_id: str) -> list[ProvenancedObservation]: ...

    def save(self, contract_id: str, observations: Sequence[ProvenancedObservation], *, source: str = ...) -> object: ...


@runtime_checkable
class HistoricalOptionIVStore(Protocol):
    def load(self, contract_id: str) -> list[ProvenancedObservation]: ...

    def save(self, contract_id: str, observations: Sequence[ProvenancedObservation], *, source: str = ...) -> object: ...


@runtime_checkable
class HistoricalOptionOpenInterestStore(Protocol):
    def load(self, contract_id: str) -> list[ProvenancedObservation]: ...

    def save(self, contract_id: str, observations: Sequence[ProvenancedObservation], *, source: str = ...) -> object: ...
