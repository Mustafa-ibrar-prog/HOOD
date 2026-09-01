"""Runs Phase 2's data-quality engine across every member of a Universe
(Phase 5, section 4). Never silently drops a symbol — a symbol with
insufficient or unavailable data is marked unavailable, WITH a reason, not
quietly excluded from the report.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.data.quality import DataQualityReport, validate_bars
from src.data.store import HistoricalDataStore
from src.data.universe import Universe


@dataclass(frozen=True)
class SymbolQualitySummary:
    symbol: str
    available: bool
    reason_unavailable: str | None
    date_range: tuple[date, date] | None
    bar_count: int
    quality_report: DataQualityReport | None
    source: str


def run_universe_quality_report(
    store: HistoricalDataStore, universe: Universe, timeframe: str, *, min_bars_required: int = 100
) -> list[SymbolQualitySummary]:
    summaries: list[SymbolQualitySummary] = []
    for symbol in universe.symbols:
        bars = store.load(symbol, timeframe)
        if not bars:
            summaries.append(SymbolQualitySummary(symbol=symbol, available=False, reason_unavailable=f"no {timeframe} data stored for {symbol}", date_range=None, bar_count=0, quality_report=None, source="none"))
            continue
        report = validate_bars(bars, stale_after_seconds=None)
        if report.status == "ERROR":
            summaries.append(SymbolQualitySummary(symbol=symbol, available=False, reason_unavailable=f"data-quality ERROR: {dict(report.counts_by_code)}", date_range=(bars[0].timestamp.date(), bars[-1].timestamp.date()), bar_count=len(bars), quality_report=report, source=bars[0].source))
            continue
        if len(bars) < min_bars_required:
            summaries.append(SymbolQualitySummary(symbol=symbol, available=False, reason_unavailable=f"only {len(bars)} bars (< {min_bars_required} required)", date_range=(bars[0].timestamp.date(), bars[-1].timestamp.date()), bar_count=len(bars), quality_report=report, source=bars[0].source))
            continue
        summaries.append(SymbolQualitySummary(symbol=symbol, available=True, reason_unavailable=None, date_range=(bars[0].timestamp.date(), bars[-1].timestamp.date()), bar_count=len(bars), quality_report=report, source=bars[0].source))
    return summaries


def usable_symbols(summaries: list[SymbolQualitySummary]) -> list[str]:
    return [s.symbol for s in summaries if s.available]


def render_universe_quality_report(summaries: list[SymbolQualitySummary]) -> str:
    lines = ["UNIVERSE DATA QUALITY REPORT", ""]
    for s in summaries:
        status = "OK" if s.available else f"UNAVAILABLE ({s.reason_unavailable})"
        range_str = f"{s.date_range[0]} -> {s.date_range[1]}" if s.date_range else "n/a"
        lines.append(f"  {s.symbol:6s} bars={s.bar_count:5d} range={range_str:26s} status={status}")
    usable = usable_symbols(summaries)
    lines.append("")
    lines.append(f"Usable: {len(usable)}/{len(summaries)} — {usable}")
    return "\n".join(lines)
