"""Phase 26, Part 4 — pure parsing functions for the real QuantConnect/
Lean options sample fetched by
`scripts/phase26_step0_fetch_actual_sample.py`.

Every function here is a deterministic, side-effect-free transform of
real, already-downloaded bytes -- nothing here fetches anything, and
nothing here invents a value: a field the file doesn't carry (e.g. no
IV/Greeks column exists anywhere in this format) simply has no parser
here, rather than a parser that returns a fabricated placeholder.

File-naming convention (confirmed via
raw.githubusercontent.com/QuantConnect/Lean/master/Data/option/readme.md,
Phase 25/26 WebFetch):
  ZIP:  YYYYMMDD_tickType_optionType.zip           (minute-resolution, per-day)
        symbol_YYYY_tickType_optionType.zip         (daily-resolution, per-year)
  CSV:  [YYYYMMDD_]symbol_[resolution_]tickType_optionType_optionStyle_
        strikeDeciCents_expirationYYYYMMDD.csv
Row format (deci-cents; divide by 10000 for dollars -- confirmed by this
phase's own real-value cross-check against known AAPL/SPY closing prices,
see docs/phase26_historical_options_dataset_certification.md Part 4):
  Quote: Time,BidOpen,BidHigh,BidLow,BidClose,LastBidSize,
         AskOpen,AskHigh,AskLow,AskClose,LastAskSize
  Trade: Time,Open,High,Low,Close,Volume
  OpenInterest: Time,OpenInterest
  Equity daily: Date,Open,High,Low,Close,Volume
"time" is milliseconds-since-midnight for minute-resolution files, and a
literal "00:00" marker (no intraday meaning) for daily-resolution files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

_FILENAME_RE = re.compile(
    r"^(?:(?P<file_date>\d{8})_)?"
    r"(?P<symbol>[a-z0-9]+)_"
    r"(?:(?P<resolution>minute|hour|daily)_)?"
    r"(?P<tick_type>quote|trade|openinterest)_"
    r"(?P<option_type>american|european)_"
    r"(?P<right>call|put)_"
    r"(?P<strike_decicents>\d+)_"
    r"(?P<expiration>\d{8})"
    r"\.csv$"
)


@dataclass(frozen=True)
class LeanContractFileMeta:
    """Everything the FILE NAME encodes about one contract's data file --
    this is the only source of contract identity in this format (no
    per-row identity column exists). `underlying_symbol` and `strike`
    come only from the filename; a caller must not assume any other
    identity field (multiplier, exercise style beyond american/european,
    exchange) is present anywhere in this data source."""

    underlying_symbol: str
    right: str  # "call" or "put"
    strike: float  # dollars
    expiration: date
    tick_type: str  # "quote" | "trade" | "openinterest"
    option_style: str  # "american" | "european"
    file_date: date | None  # the per-day zip's date, for minute-resolution files only


def parse_lean_option_filename(filename: str) -> LeanContractFileMeta:
    m = _FILENAME_RE.match(filename)
    if not m:
        raise ValueError(f"filename does not match the known Lean options CSV naming convention: {filename!r}")
    g = m.groupdict()
    strike = int(g["strike_decicents"]) / 10000.0
    expiration = datetime.strptime(g["expiration"], "%Y%m%d").date()
    file_date = datetime.strptime(g["file_date"], "%Y%m%d").date() if g["file_date"] else None
    return LeanContractFileMeta(
        underlying_symbol=g["symbol"].upper(),
        right=g["right"],
        strike=strike,
        expiration=expiration,
        tick_type=g["tick_type"],
        option_style=g["option_type"],
        file_date=file_date,
    )


def _parse_lean_timestamp(date_part: str, time_part: str) -> datetime:
    """`date_part` is YYYYMMDD; `time_part` is either a literal "00:00"
    (daily resolution -- no intraday meaning, midnight is a placeholder,
    never treated as a real observation time) or HH:MM (already resolved
    from ms-since-midnight by the caller)."""
    base = datetime.strptime(date_part, "%Y%m%d")
    hh, mm = time_part.split(":")
    return base + timedelta(hours=int(hh), minutes=int(mm))


@dataclass(frozen=True)
class LeanQuoteRow:
    """A bid_*/ask_* field is None when that side of the market was
    genuinely unquoted on this real row (see `_parse_optional_decicents`)
    -- never coerced to 0.0."""

    timestamp: datetime
    bid_open: float | None
    bid_high: float | None
    bid_low: float | None
    bid_close: float | None
    last_bid_size: int
    ask_open: float | None
    ask_high: float | None
    ask_low: float | None
    ask_close: float | None
    last_ask_size: int
    is_daily_resolution: bool  # True if the source row's Time field was a bare "00:00" placeholder


@dataclass(frozen=True)
class LeanTradeRow:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    is_daily_resolution: bool


@dataclass(frozen=True)
class LeanOpenInterestRow:
    timestamp: datetime
    open_interest: int
    is_daily_resolution: bool


@dataclass(frozen=True)
class LeanEquityBar:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


def _resolve_time_field(file_date: date | None, raw_time: str) -> tuple[datetime, bool]:
    """`raw_time` is either "YYYYMMDD 00:00" (daily rows carry the date
    inline) or a bare millisecond count (minute rows -- the date comes
    from the containing zip's file_date, since minute-resolution CSVs
    don't repeat the date per row)."""
    if " " in raw_time:
        date_part, time_part = raw_time.split(" ")
        return _parse_lean_timestamp(date_part, time_part), True
    ms = int(raw_time)
    if file_date is None:
        raise ValueError("a millisecond-since-midnight time field requires a known file_date (minute resolution)")
    base = datetime(file_date.year, file_date.month, file_date.day)
    return base + timedelta(milliseconds=ms), False


def _parse_optional_decicents(raw: str) -> float | None:
    """A REAL, observed phenomenon in this data source (Phase 26 finding,
    not a parsing bug): a one-sided market (no bid or no ask quoted that
    day) is represented as an EMPTY field, not a zero. An empty field
    means "no quote was posted on that side" -- it must stay None, never
    coerced to 0.0 (which would look like a real, absurdly-low quote)."""
    raw = raw.strip()
    if raw == "":
        return None
    return int(raw) / 10000.0


def parse_lean_quote_row(line: str, file_date: date | None) -> LeanQuoteRow:
    parts = line.strip().split(",")
    if len(parts) != 11:
        raise ValueError(f"expected 11 quote columns, got {len(parts)}: {line!r}")
    timestamp, is_daily = _resolve_time_field(file_date, parts[0])
    vals = [_parse_optional_decicents(p) for p in parts[1:5]]
    last_bid_size = int(parts[5])
    ask_vals = [_parse_optional_decicents(p) for p in parts[6:10]]
    last_ask_size = int(parts[10])
    return LeanQuoteRow(
        timestamp=timestamp,
        bid_open=vals[0], bid_high=vals[1], bid_low=vals[2], bid_close=vals[3],
        last_bid_size=last_bid_size,
        ask_open=ask_vals[0], ask_high=ask_vals[1], ask_low=ask_vals[2], ask_close=ask_vals[3],
        last_ask_size=last_ask_size,
        is_daily_resolution=is_daily,
    )


def parse_lean_trade_row(line: str, file_date: date | None) -> LeanTradeRow:
    parts = line.strip().split(",")
    if len(parts) != 6:
        raise ValueError(f"expected 6 trade columns, got {len(parts)}: {line!r}")
    timestamp, is_daily = _resolve_time_field(file_date, parts[0])
    vals = [int(p) / 10000.0 for p in parts[1:5]]
    volume = int(parts[5])
    return LeanTradeRow(
        timestamp=timestamp, open=vals[0], high=vals[1], low=vals[2], close=vals[3],
        volume=volume, is_daily_resolution=is_daily,
    )


def parse_lean_oi_row(line: str, file_date: date | None) -> LeanOpenInterestRow:
    parts = line.strip().split(",")
    if len(parts) != 2:
        raise ValueError(f"expected 2 open-interest columns, got {len(parts)}: {line!r}")
    timestamp, is_daily = _resolve_time_field(file_date, parts[0])
    return LeanOpenInterestRow(timestamp=timestamp, open_interest=int(parts[1]), is_daily_resolution=is_daily)


def parse_lean_equity_row(line: str) -> LeanEquityBar:
    parts = line.strip().split(",")
    if len(parts) != 6:
        raise ValueError(f"expected 6 equity columns, got {len(parts)}: {line!r}")
    date_part = parts[0].split(" ")[0]
    d = datetime.strptime(date_part, "%Y%m%d").date()
    vals = [int(p) / 10000.0 for p in parts[1:5]]
    volume = int(parts[5])
    return LeanEquityBar(date=d, open=vals[0], high=vals[1], low=vals[2], close=vals[3], volume=volume)
