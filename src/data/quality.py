"""Data-quality validation for historical Bar series — run BEFORE any
research or backtesting code is allowed to trust a dataset.

Deliberately never "fixes" anything: every check below only detects and
reports. A caller that wants clean data re-fetches or explicitly filters
after reading the report — same "never silently paper over a problem"
convention as this codebase's other stores (risk/store.py,
execution/pending.py fail closed rather than guess).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence

from src.data.bar import Bar

# Expected spacing between consecutive bars, by HOOD interval string — used
# only to size the missing-interval/suspicious-gap heuristic below. An
# unrecognized timeframe simply skips the gap checks (still runs every
# other check) rather than guessing a spacing.
_TIMEFRAME_SECONDS = {
    "1minute": 60,
    "5minute": 300,
    "10minute": 600,
    "15minute": 900,
    "30minute": 1800,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
}


@dataclass(frozen=True)
class DataQualityIssue:
    code: str
    severity: str  # "ERROR" | "WARNING"
    message: str
    timestamp: datetime | None = None


@dataclass(frozen=True)
class DataQualityReport:
    symbol: str
    timeframe: str
    record_count: int
    issues: tuple[DataQualityIssue, ...] = field(default_factory=tuple)

    @property
    def counts_by_code(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.code] = counts.get(issue.code, 0) + 1
        return counts

    @property
    def status(self) -> str:
        if any(i.severity == "ERROR" for i in self.issues):
            return "ERROR"
        if self.issues:
            return "WARNING"
        return "OK"

    def render(self) -> str:
        """Human-readable report in the format specified for this phase."""
        counts = self.counts_by_code
        lines = [
            "Dataset:",
            f"  {self.symbol}",
            f"  {self.timeframe}",
            "",
            "Records:",
            f"  {self.record_count:,}",
            "",
        ]
        for label, code in (
            ("Missing intervals", "MISSING_INTERVAL"),
            ("Suspicious gaps", "SUSPICIOUS_GAP"),
            ("Duplicate timestamps", "DUPLICATE_TIMESTAMP"),
            ("Duplicate records", "DUPLICATE_RECORD"),
            ("Invalid OHLC records", "INVALID_OHLC"),
            ("Negative prices", "NEGATIVE_PRICE"),
            ("Zero/invalid prices", "INVALID_PRICE"),
            ("Impossible volume", "INVALID_VOLUME"),
            ("Timezone issues", "TIMEZONE_ISSUE"),
            ("Out-of-order records", "OUT_OF_ORDER"),
            ("Stale data", "STALE_DATA"),
        ):
            lines.append(f"{label}:")
            lines.append(f"  {counts.get(code, 0)}")
        lines.append("")
        lines.append("Status:")
        lines.append(f"  {self.status}")
        return "\n".join(lines)


def validate_bars(
    bars: Sequence[Bar],
    *,
    symbol: str | None = None,
    timeframe: str | None = None,
    gap_multiplier: float = 1.5,
    large_gap_seconds: float = 4 * 3600,
    stale_after_seconds: float | None = None,
    now: datetime | None = None,
) -> DataQualityReport:
    """Runs every documented check over `bars` (assumed to be one symbol's
    one-timeframe series — mixed input is itself flagged as a mismatch,
    not silently accepted).

    Gap classification is a heuristic, not calendar-aware: this codebase
    has no trading-calendar/session-boundary model, so a normal overnight
    or weekend gap in real market-hours data is NOT distinguished from a
    genuinely suspicious intraday gap — both are flagged, with
    `large_gap_seconds` splitting "small enough to just count as missing
    bars" (MISSING_INTERVAL) from "large enough to call out separately"
    (SUSPICIOUS_GAP). A future trading-calendar-aware version could narrow
    this false-positive rate on overnight/weekend boundaries; see the
    Phase 2 report's "remaining limitations" section.
    """
    issues: list[DataQualityIssue] = []
    symbol = symbol or (bars[0].symbol if bars else "UNKNOWN")
    timeframe = timeframe or (bars[0].timeframe if bars else "UNKNOWN")

    if not bars:
        return DataQualityReport(symbol=symbol, timeframe=timeframe, record_count=0, issues=())

    for b in bars:
        if b.symbol != symbol:
            issues.append(
                DataQualityIssue("SYMBOL_MISMATCH", "ERROR", f"bar for {b.symbol!r} in a {symbol!r} dataset", b.timestamp)
            )
        if b.timeframe != timeframe:
            issues.append(
                DataQualityIssue(
                    "TIMEFRAME_MISMATCH", "ERROR", f"bar with timeframe {b.timeframe!r} in a {timeframe!r} dataset", b.timestamp
                )
            )
        if b.timestamp.tzinfo is None or b.timestamp.utcoffset().total_seconds() != 0:
            issues.append(DataQualityIssue("TIMEZONE_ISSUE", "ERROR", "bar timestamp is not UTC/timezone-aware", b.timestamp))
        if b.open < 0 or b.high < 0 or b.low < 0 or b.close < 0:
            issues.append(DataQualityIssue("NEGATIVE_PRICE", "ERROR", "a price field is negative", b.timestamp))
        elif b.open == 0 or b.high == 0 or b.low == 0 or b.close == 0:
            issues.append(
                DataQualityIssue("INVALID_PRICE", "ERROR", "a price field is zero (invalid for a traded instrument)", b.timestamp)
            )
        if b.volume < 0:
            issues.append(DataQualityIssue("INVALID_VOLUME", "ERROR", f"negative volume ({b.volume})", b.timestamp))
        # high >= max(open, close, low); low <= min(open, close, high) — the exact
        # relationship specified for this check.
        if b.high < max(b.open, b.close, b.low) or b.low > min(b.open, b.close, b.high):
            issues.append(
                DataQualityIssue(
                    "INVALID_OHLC",
                    "ERROR",
                    f"OHLC relationship violated (o={b.open} h={b.high} l={b.low} c={b.close})",
                    b.timestamp,
                )
            )

    seen_ts: dict[datetime, int] = {}
    for b in bars:
        seen_ts[b.timestamp] = seen_ts.get(b.timestamp, 0) + 1
    for ts, count in seen_ts.items():
        if count > 1:
            issues.append(DataQualityIssue("DUPLICATE_TIMESTAMP", "ERROR", f"{count} bars share timestamp {ts.isoformat()}", ts))

    seen_rows: dict[tuple, int] = {}
    for b in bars:
        key = (b.timestamp, b.open, b.high, b.low, b.close, b.volume)
        seen_rows[key] = seen_rows.get(key, 0) + 1
    for key, count in seen_rows.items():
        if count > 1:
            issues.append(DataQualityIssue("DUPLICATE_RECORD", "WARNING", f"{count} fully-identical rows at {key[0].isoformat()}", key[0]))

    ordered = sorted(bars, key=lambda b: b.timestamp)
    if list(ordered) != list(bars):
        issues.append(DataQualityIssue("OUT_OF_ORDER", "ERROR", "bars are not sorted ascending by timestamp"))

    expected_seconds = _TIMEFRAME_SECONDS.get(timeframe)
    if expected_seconds:
        for i in range(1, len(ordered)):
            gap = (ordered[i].timestamp - ordered[i - 1].timestamp).total_seconds()
            if gap <= 0:
                continue
            if gap > large_gap_seconds:
                issues.append(
                    DataQualityIssue(
                        "SUSPICIOUS_GAP", "WARNING", f"{gap / 3600:.1f}h gap ending {ordered[i].timestamp.isoformat()}", ordered[i].timestamp
                    )
                )
            elif gap > expected_seconds * gap_multiplier:
                missing = round(gap / expected_seconds) - 1
                if missing > 0:
                    issues.append(
                        DataQualityIssue(
                            "MISSING_INTERVAL",
                            "WARNING",
                            f"~{missing} missing bar(s) before {ordered[i].timestamp.isoformat()}",
                            ordered[i].timestamp,
                        )
                    )

    if stale_after_seconds is not None:
        now = now or datetime.now(timezone.utc)
        last = ordered[-1].timestamp
        age = (now - last).total_seconds()
        if age > stale_after_seconds:
            issues.append(
                DataQualityIssue(
                    "STALE_DATA", "WARNING", f"most recent bar is {age / 3600:.1f}h old (limit {stale_after_seconds / 3600:.1f}h)", last
                )
            )

    return DataQualityReport(symbol=symbol, timeframe=timeframe, record_count=len(bars), issues=tuple(issues))
