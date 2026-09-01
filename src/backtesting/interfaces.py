"""Data-source interfaces and the backtest configuration record.

No execution loop, no strategy runner, no optimizer lives here. Nothing
in this module is imported by src/orchestrator.py or any live/paper
trading code — see engine.py's module docstring for the explicit
backtest/paper/live execution boundary.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol, Sequence, runtime_checkable

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
    """The full, serializable record of what a backtest run was — every
    result must preserve this (Phase 3, sections 20-21). Fully backward
    compatible with Phase 2's placeholder: the original 6 fields keep
    their exact names, types, and (for the last two) defaults.

    Model INSTANCES (execution model, slippage model, cost model, spread
    model, position sizer, risk manager) are passed to BacktestEngine
    separately — they're behavior, not data, and aren't meaningfully
    reconstructible from a plain dict alone. The *_config fields here are
    a human/machine-readable summary of what was actually used (class name
    + parameters), which is what gets recorded for reproducibility
    (src.research.experiment.ExperimentStore) — reconstructing the actual
    model objects from that summary is a manual step today, not an
    automated deserialization registry (a real limitation, noted in the
    Phase 3 report rather than silently glossed over).
    """

    symbols: tuple[str, ...]
    timeframe: str
    start: date
    end: date
    data_version: str
    feature_version: str
    strategy_version: str | None = None
    initial_capital_usd: float = 0.0

    backtest_id: str = field(default_factory=lambda: f"BT-{uuid.uuid4().hex[:12]}")
    strategy_name: str = ""
    benchmark_symbol: str | None = None
    execution_config: dict[str, Any] = field(default_factory=dict)
    slippage_config: dict[str, Any] = field(default_factory=dict)
    cost_config: dict[str, Any] = field(default_factory=dict)
    spread_config: dict[str, Any] = field(default_factory=dict)
    sizing_config: dict[str, Any] = field(default_factory=dict)
    risk_config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "backtest_id": self.backtest_id,
            "symbols": list(self.symbols),
            "timeframe": self.timeframe,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "data_version": self.data_version,
            "feature_version": self.feature_version,
            "strategy_version": self.strategy_version,
            "strategy_name": self.strategy_name,
            "initial_capital_usd": self.initial_capital_usd,
            "benchmark_symbol": self.benchmark_symbol,
            "execution_config": self.execution_config,
            "slippage_config": self.slippage_config,
            "cost_config": self.cost_config,
            "spread_config": self.spread_config,
            "sizing_config": self.sizing_config,
            "risk_config": self.risk_config,
        }
