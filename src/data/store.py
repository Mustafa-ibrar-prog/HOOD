"""Local, file-backed historical bar storage.

One dataset = one (symbol, timeframe) pair, stored as a sorted,
deduplicated JSONL file plus a metadata sidecar. This module never fetches
anything itself — same "nothing in this Python process can call a HOOD MCP
tool" boundary as everywhere else in this codebase (see src/live_bridge.py's
module docstring). Callers (the orchestrating agent, via a research script)
fetch real historical bars, build `Bar` objects (src/data/bar.py), and hand
them to `save()`/`upsert()`.

Same fail-closed convention as every other store in this codebase
(risk/store.py, position_manager/store.py, execution/pending.py): a
corrupted dataset or metadata file raises rather than silently being
treated as empty and re-downloaded/overwritten without anyone noticing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from src.data.bar import Bar
from src.data.versioning import compute_data_version


class HistoricalDataStoreError(RuntimeError):
    """Raised when a persisted dataset or its metadata can't be trusted."""


@dataclass(frozen=True)
class DatasetMetadata:
    symbol: str
    timeframe: str
    source: str
    start_timestamp: datetime
    end_timestamp: datetime
    downloaded_at: datetime
    record_count: int
    data_version: str

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "source": self.source,
            "start_timestamp": self.start_timestamp.isoformat(),
            "end_timestamp": self.end_timestamp.isoformat(),
            "downloaded_at": self.downloaded_at.isoformat(),
            "record_count": self.record_count,
            "data_version": self.data_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DatasetMetadata":
        return cls(
            symbol=data["symbol"],
            timeframe=data["timeframe"],
            source=data["source"],
            start_timestamp=datetime.fromisoformat(data["start_timestamp"]),
            end_timestamp=datetime.fromisoformat(data["end_timestamp"]),
            downloaded_at=datetime.fromisoformat(data["downloaded_at"]),
            record_count=int(data["record_count"]),
            data_version=data["data_version"],
        )


class HistoricalDataStore:
    def __init__(self, root_dir: Path):
        self._root = Path(root_dir)

    def _dataset_dir(self, symbol: str, timeframe: str) -> Path:
        return self._root / symbol.upper() / timeframe

    def _data_path(self, symbol: str, timeframe: str) -> Path:
        return self._dataset_dir(symbol, timeframe) / "bars.jsonl"

    def _meta_path(self, symbol: str, timeframe: str) -> Path:
        return self._dataset_dir(symbol, timeframe) / "metadata.json"

    def list_datasets(self) -> list[tuple[str, str]]:
        if not self._root.is_dir():
            return []
        out: list[tuple[str, str]] = []
        for symbol_dir in sorted(p for p in self._root.iterdir() if p.is_dir()):
            for tf_dir in sorted(p for p in symbol_dir.iterdir() if p.is_dir()):
                if (tf_dir / "bars.jsonl").is_file():
                    out.append((symbol_dir.name, tf_dir.name))
        return out

    def load(self, symbol: str, timeframe: str) -> list[Bar]:
        path = self._data_path(symbol, timeframe)
        if not path.is_file():
            return []
        raw = path.read_text()
        if not raw.strip():
            return []
        try:
            return [Bar.from_dict(json.loads(line)) for line in raw.splitlines() if line.strip()]
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise HistoricalDataStoreError(f"Dataset {symbol}/{timeframe} is corrupted or unreadable: {exc}") from exc

    def load_metadata(self, symbol: str, timeframe: str) -> DatasetMetadata | None:
        path = self._meta_path(symbol, timeframe)
        if not path.is_file():
            return None
        raw = path.read_text()
        if not raw.strip():
            return None
        try:
            return DatasetMetadata.from_dict(json.loads(raw))
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise HistoricalDataStoreError(f"Metadata for {symbol}/{timeframe} is corrupted or unreadable: {exc}") from exc

    def existing_range(self, symbol: str, timeframe: str) -> tuple[datetime, datetime] | None:
        meta = self.load_metadata(symbol, timeframe)
        if meta is None:
            return None
        return (meta.start_timestamp, meta.end_timestamp)

    def needs_download(self, symbol: str, timeframe: str, requested_start: datetime, requested_end: datetime) -> bool:
        """True if the requested [start, end] window is not already fully
        covered by what's stored — the check a caller should make BEFORE
        fetching, to avoid unnecessary duplicate downloads."""
        existing = self.existing_range(symbol, timeframe)
        if existing is None:
            return True
        have_start, have_end = existing
        return requested_start < have_start or requested_end > have_end

    def save(self, symbol: str, timeframe: str, bars: Sequence[Bar], *, source: str = "hood") -> DatasetMetadata:
        """Full overwrite of one dataset with `bars` (deduplicated and
        sorted by timestamp)."""
        return self._write(symbol, timeframe, self._dedupe_sorted(bars), source=source)

    def upsert(self, symbol: str, timeframe: str, new_bars: Sequence[Bar], *, source: str = "hood") -> DatasetMetadata:
        """Merges `new_bars` into whatever is already stored for this
        (symbol, timeframe), keyed by timestamp. On a timestamp collision,
        `new_bars` wins (a fresh re-fetch is assumed more authoritative
        than what was stored before). This is the incremental-update path:
        a caller fetches only the gap (see needs_download/existing_range)
        and upserts just that gap in, rather than re-downloading and
        re-saving the whole history every time."""
        existing = self.load(symbol, timeframe)
        by_ts = {b.timestamp: b for b in existing}
        for b in new_bars:
            by_ts[b.timestamp] = b
        merged = sorted(by_ts.values(), key=lambda b: b.timestamp)
        return self._write(symbol, timeframe, merged, source=source)

    def _dedupe_sorted(self, bars: Sequence[Bar]) -> list[Bar]:
        by_ts: dict[datetime, Bar] = {}
        for b in bars:
            by_ts[b.timestamp] = b
        return sorted(by_ts.values(), key=lambda b: b.timestamp)

    def _write(self, symbol: str, timeframe: str, bars: list[Bar], *, source: str) -> DatasetMetadata:
        directory = self._dataset_dir(symbol, timeframe)
        directory.mkdir(parents=True, exist_ok=True)
        data_path = self._data_path(symbol, timeframe)
        with data_path.open("w") as f:
            for b in bars:
                f.write(json.dumps(b.to_dict(), sort_keys=True))
                f.write("\n")

        now = datetime.now(timezone.utc)
        if bars:
            start_ts, end_ts = bars[0].timestamp, bars[-1].timestamp
        else:
            start_ts = end_ts = now
        data_version = compute_data_version(
            source=source,
            symbol=symbol.upper(),
            timeframe=timeframe,
            start=start_ts.isoformat(),
            end=end_ts.isoformat(),
            record_count=len(bars),
        )
        meta = DatasetMetadata(
            symbol=symbol.upper(),
            timeframe=timeframe,
            source=source,
            start_timestamp=start_ts,
            end_timestamp=end_ts,
            downloaded_at=now,
            record_count=len(bars),
            data_version=data_version,
        )
        self._meta_path(symbol, timeframe).write_text(json.dumps(meta.to_dict(), indent=2, sort_keys=True))
        return meta
