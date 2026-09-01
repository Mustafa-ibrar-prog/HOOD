"""Interfaces only — Phase 1's audit confirmed no backtesting engine
exists yet, and per this phase's explicit scope, building one is Phase
3's job, not this one. This module defines the seam a future engine will
use to read historical bars, and the config shape a backtest run will
need to record against src.research.experiment.ExperimentStore, so Phase
3 has a stable contract to build against without this phase guessing at
engine internals it isn't meant to build.

No execution loop, no strategy runner, no optimizer lives here. Nothing
in this module is imported by src/orchestrator.py or any live/paper
trading code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, Sequence, runtime_checkable

from src.data.bar import Bar
from src.data.store import HistoricalDataStore


@runtime_checkable
class HistoricalBarSource(Protocol):
    """What a future backtest engine needs from a data layer: bars for one
    symbol/timeframe over a date range. @runtime_checkable so a Phase 3
    engine (or a test) can isinstance()-check a concrete implementation
    against this contract."""

    def get_bars(self, symbol: str, timeframe: str, start: date, end: date) -> Sequence[Bar]: ...


class StoreBackedBarSource:
    """Concrete HistoricalBarSource backed by HistoricalDataStore — the
    thin adapter Phase 3's engine will actually use. Does no fetching
    itself; filters what's already stored down to [start, end] by date."""

    def __init__(self, store: HistoricalDataStore):
        self._store = store

    def get_bars(self, symbol: str, timeframe: str, start: date, end: date) -> Sequence[Bar]:
        bars = self._store.load(symbol, timeframe)
        return [b for b in bars if start <= b.timestamp.date() <= end]


@dataclass(frozen=True)
class BacktestConfig:
    """Placeholder config shape for Phase 3 — captured now so research
    experiments (src.research.experiment.ExperimentRecord) have a stable
    field set to record against once a real backtest engine exists. Not
    consumed by any engine yet."""

    symbols: tuple[str, ...]
    timeframe: str
    start: date
    end: date
    data_version: str
    feature_version: str
    strategy_version: str | None = None
    initial_capital_usd: float = 0.0
