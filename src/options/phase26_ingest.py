"""Phase 26, Part 4/12 — loads the real, already-fetched QuantConnect/
Lean sample files (`logs/research_data/phase26_raw/extracted/`) off disk
and builds an `InMemoryLeanSampleStore` from them. This is the only
module in this phase that touches the filesystem for raw CSVs; every
other Phase 26 module operates on already-parsed, in-memory structures.

`adjustment_status` honesty note (Part 3/8): this phase found REAL
evidence that AlgoSeek/Lean does NOT retroactively re-adjust legacy
contracts after a split -- the same expiration (2015-01-17) carries BOTH
pre-split-era fractional strikes (e.g. $28.57 = $200/7, a real remnant of
AAPL's June 2014 7-for-1 split) AND new post-split round-dollar strikes
(e.g. $103) side by side, and a $1000-strike 2015-01-17 call's real data
row stops dead on 2014-06-06 (the trading day before the split), never
resuming under that identity. This is reported as REAL, OBSERVED
evidence, not inferred from vendor documentation (none was reachable)
-- see docs/phase26_historical_options_dataset_certification.md Part 8.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from src.options.phase26_dataset_builder import (
    InMemoryLeanSampleStore,
    build_contract_identity,
    build_contract_lifecycle,
    build_provenance,
    contract_id_for,
    open_interest_observation,
    quote_observations,
    trade_observations,
    underlying_observations,
)
from src.options.phase26_lean_sample_parser import (
    parse_lean_equity_row,
    parse_lean_oi_row,
    parse_lean_option_filename,
    parse_lean_quote_row,
    parse_lean_trade_row,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_EXTRACTED_DIR = REPO_ROOT / "logs/research_data/phase26_raw/extracted"

ADJUSTMENT_STATUS_NOTE = (
    "raw_as_listed_no_retroactive_reconciliation_observed -- real evidence this phase: legacy pre-split "
    "fractional strikes and new post-split round-dollar strikes coexist under the same real expiration date"
)


def _load_option_csv_dir(directory: Path, tick_type: str) -> list[tuple]:
    """Returns a list of (LeanContractFileMeta, list[row]) for every CSV
    in `directory` whose filename matches `tick_type`. Skips nothing
    silently -- a filename that fails to parse raises, it is not dropped."""
    out = []
    for path in sorted(directory.glob("*.csv")):
        meta = parse_lean_option_filename(path.name)
        if meta.tick_type != tick_type:
            continue
        lines = [line for line in path.read_text().splitlines() if line.strip()]
        if tick_type == "quote":
            rows = [parse_lean_quote_row(line, meta.file_date) for line in lines]
        elif tick_type == "trade":
            rows = [parse_lean_trade_row(line, meta.file_date) for line in lines]
        else:
            rows = [parse_lean_oi_row(line, meta.file_date) for line in lines]
        out.append((meta, rows))
    return out


def build_store_from_directories(
    *,
    quote_dirs: list[Path] = (),
    trade_dirs: list[Path] = (),
    oi_dirs: list[Path] = (),
    equity_files: dict[str, Path] = None,
    retrieval_timestamp: datetime,
    today: date,
) -> InMemoryLeanSampleStore:
    equity_files = equity_files or {}
    provenance = build_provenance(retrieval_timestamp=retrieval_timestamp, adjustment_status=ADJUSTMENT_STATUS_NOTE)

    contracts: dict = {}
    lifecycles: dict = {}
    quotes: dict = defaultdict(list)
    trades: dict = defaultdict(list)
    open_interest: dict = defaultdict(list)
    underlying: dict = defaultdict(list)

    def _register_contract(meta, observed_dates: list[date]) -> str:
        cid = contract_id_for(meta)
        if cid not in contracts:
            contracts[cid] = build_contract_identity(meta, provenance)
        if observed_dates:
            existing = lifecycles.get(cid)
            all_dates = list(observed_dates)
            if existing is not None:
                all_dates += [existing.first_observable_date, existing.last_trade_date]
            lifecycles[cid] = build_contract_lifecycle(meta, all_dates, provenance, today=today)
        return cid

    for d in quote_dirs:
        for meta, rows in _load_option_csv_dir(Path(d), "quote"):
            cid = _register_contract(meta, [r.timestamp.date() for r in rows])
            for row in rows:
                quotes[cid].extend(quote_observations(cid, row, ingestion_time=retrieval_timestamp))

    for d in trade_dirs:
        for meta, rows in _load_option_csv_dir(Path(d), "trade"):
            cid = _register_contract(meta, [r.timestamp.date() for r in rows])
            for row in rows:
                trades[cid].extend(trade_observations(cid, row, ingestion_time=retrieval_timestamp))

    for d in oi_dirs:
        for meta, rows in _load_option_csv_dir(Path(d), "openinterest"):
            cid = _register_contract(meta, [r.timestamp.date() for r in rows])
            for row in rows:
                open_interest[cid].append(open_interest_observation(cid, row, ingestion_time=retrieval_timestamp))

    for symbol, path in equity_files.items():
        lines = [line for line in Path(path).read_text().splitlines() if line.strip()]
        bars = [parse_lean_equity_row(line) for line in lines]
        for bar in bars:
            underlying[symbol].extend(underlying_observations(symbol, bar, ingestion_time=retrieval_timestamp))

    return InMemoryLeanSampleStore(
        contracts=contracts, lifecycles=lifecycles, quotes=dict(quotes), trades=dict(trades),
        open_interest=dict(open_interest), underlying=dict(underlying),
    )
