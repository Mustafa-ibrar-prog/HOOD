"""Phase 15, Part 12 — conceptual store interfaces for future data types.

`HistoricalBarStore` is a structural (typing.Protocol) description of the
REAL, EXISTING `src.data.store.HistoricalDataStore` — written to prove, by
construction, that today's Bar storage already satisfies the same shape a
future store should follow, not to replace it. `HistoricalDataStore`
itself is unmodified; nothing here changes its behavior.

`QuoteStore`, `TradeStore`, `FundamentalStore`, `EarningsStore`,
`OptionsStore`, and `MacroStore` are the genuinely NEW interfaces Part 12
asks for. Per its explicit "do not overengineer" instruction, they share
ONE generic record shape (`ProvenancedObservation`, below) rather than six
bespoke schemas invented ahead of actually picking a concrete source in a
future phase — every one of Phase 15's audited candidate sources (Part 4)
needs the exact same discipline (a natural key, a field name, a value, an
`EventTimestamps`, and a provenance label), and the differences between
them are in WHICH concrete store class and WHICH `CausalTimestampPolicy`
apply, not in the record shape itself. No concrete class implements any
of these six Protocols yet — that is deliberate: Phase 15 is architecture
only (Part 1), and a concrete implementation belongs to whichever future
phase actually adopts one of the ranked candidate sources.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable

from src.data.bar import Bar
from src.data.source_profile import DataProvenance
from src.data.timestamp_model import EventTimestamps


@dataclass(frozen=True)
class ProvenancedObservation:
    """One observation from any non-Bar data source. `key` is whatever
    that source's natural identifier is (a stock symbol for fundamentals/
    earnings, an option contract id, a macro series id, ...). `field` is
    the specific metric ("revenue", "eps_actual", "cpi_yoy", "bid", ...).
    Deliberately flat and source-agnostic — see module docstring."""

    key: str
    field: str
    value: float | str | None
    timestamps: EventTimestamps
    provenance: DataProvenance
    source: str


@runtime_checkable
class HistoricalBarStore(Protocol):
    """Matches src.data.store.HistoricalDataStore's real public surface —
    a structural proof that the existing store already fits this shape."""

    def load(self, symbol: str, timeframe: str) -> list[Bar]: ...

    def save(self, symbol: str, timeframe: str, bars: Sequence[Bar], *, source: str = ...) -> object: ...

    def list_datasets(self) -> list[tuple[str, str]]: ...


@runtime_checkable
class QuoteStore(Protocol):
    def load(self, symbol: str) -> list[ProvenancedObservation]: ...

    def save(self, symbol: str, observations: Sequence[ProvenancedObservation], *, source: str = ...) -> object: ...


@runtime_checkable
class TradeStore(Protocol):
    def load(self, symbol: str) -> list[ProvenancedObservation]: ...

    def save(self, symbol: str, observations: Sequence[ProvenancedObservation], *, source: str = ...) -> object: ...


@runtime_checkable
class FundamentalStore(Protocol):
    def load(self, symbol: str) -> list[ProvenancedObservation]: ...

    def save(self, symbol: str, observations: Sequence[ProvenancedObservation], *, source: str = ...) -> object: ...


@runtime_checkable
class EarningsStore(Protocol):
    def load(self, symbol: str) -> list[ProvenancedObservation]: ...

    def save(self, symbol: str, observations: Sequence[ProvenancedObservation], *, source: str = ...) -> object: ...


@runtime_checkable
class OptionsStore(Protocol):
    def load(self, contract_id: str) -> list[ProvenancedObservation]: ...

    def save(self, contract_id: str, observations: Sequence[ProvenancedObservation], *, source: str = ...) -> object: ...


@runtime_checkable
class MacroStore(Protocol):
    def load(self, series_id: str) -> list[ProvenancedObservation]: ...

    def save(self, series_id: str, observations: Sequence[ProvenancedObservation], *, source: str = ...) -> object: ...
