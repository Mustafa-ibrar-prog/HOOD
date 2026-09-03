"""Phase 27, Part 1/7 — the expanded ingestion entrypoint.

Reuses Phase 26's real, already-certified per-file parsing and
per-observation construction helpers (`phase26_ingest._load_option_csv_dir`,
`phase26_dataset_builder.*`) rather than rewriting them (Part 1: "do not
rewrite working components unnecessarily") -- the ONLY thing this module
adds is routing every contract's observations through Phase 27's new
`phase27_merge` layer instead of Phase 26's simpler dict-extend, which is
what a real bug this phase found (see phase27_merge.py's module
docstring) requires once multiple resolutions/directories for the same
contract are combined.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from src.options.phase26_dataset_builder import (
    build_contract_identity,
    build_contract_lifecycle,
    build_provenance,
    contract_id_for,
    open_interest_observation,
    quote_observations,
    trade_observations,
    underlying_observations,
)
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.phase26_ingest import ADJUSTMENT_STATUS_NOTE, _load_option_csv_dir  # reused, not reimplemented
from src.options.phase26_lean_sample_parser import parse_lean_equity_row
from src.options.phase27_merge import MergeConflict, merged_quotes_by_contract

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PHASE26_RAW_EXTRACTED_DIR = REPO_ROOT / "logs/research_data/phase26_raw/extracted"
PHASE27_RAW_EXTRACTED_DIR = REPO_ROOT / "logs/research_data/phase27_raw/extracted"


def build_expanded_store_from_directories(
    *,
    quote_dirs: list[Path] = (),
    trade_dirs: list[Path] = (),
    oi_dirs: list[Path] = (),
    equity_files: dict[str, Path] = None,
    retrieval_timestamp: datetime,
    today: date,
) -> tuple[InMemoryLeanSampleStore, list[MergeConflict]]:
    """Same real-data-only contract as Phase 26's
    `build_store_from_directories`, but (a) accepts directories spanning
    multiple resolutions/underlyings/dates for the SAME contract and (b)
    routes every contract's per-field observation list through the
    deterministic merge layer, returning the conflict log alongside the
    store (Part 7: conflicts are surfaced, never silently resolved)."""
    equity_files = equity_files or {}
    provenance = build_provenance(retrieval_timestamp=retrieval_timestamp, adjustment_status=ADJUSTMENT_STATUS_NOTE)

    contracts: dict = {}
    contract_meta_seen: dict = {}  # cid -> the first LeanContractFileMeta identity fields seen, for a consistency check
    observed_dates_by_contract: dict = defaultdict(list)
    raw_quote_dicts: list[dict] = []
    raw_trade_dicts: list[dict] = []
    raw_oi_dicts: list[dict] = []
    underlying: dict = defaultdict(list)

    def _register(meta, observed_dates: list[date]) -> str:
        cid = contract_id_for(meta)
        identity_fields = (meta.underlying_symbol, meta.right, meta.strike, meta.expiration, meta.option_style)
        if cid in contract_meta_seen and contract_meta_seen[cid] != identity_fields:
            raise ValueError(f"contract identity mismatch for {cid}: {contract_meta_seen[cid]} vs {identity_fields}")
        contract_meta_seen[cid] = identity_fields
        if cid not in contracts:
            contracts[cid] = build_contract_identity(meta, provenance)
        observed_dates_by_contract[cid].extend(observed_dates)
        return cid

    for d in quote_dirs:
        per_dir_quotes: dict = defaultdict(list)
        for meta, rows in _load_option_csv_dir(Path(d), "quote"):
            cid = _register(meta, [r.timestamp.date() for r in rows])
            for row in rows:
                per_dir_quotes[cid].extend(quote_observations(cid, row, ingestion_time=retrieval_timestamp))
        raw_quote_dicts.append(dict(per_dir_quotes))

    for d in trade_dirs:
        per_dir_trades: dict = defaultdict(list)
        for meta, rows in _load_option_csv_dir(Path(d), "trade"):
            cid = _register(meta, [r.timestamp.date() for r in rows])
            for row in rows:
                per_dir_trades[cid].extend(trade_observations(cid, row, ingestion_time=retrieval_timestamp))
        raw_trade_dicts.append(dict(per_dir_trades))

    for d in oi_dirs:
        per_dir_oi: dict = defaultdict(list)
        for meta, rows in _load_option_csv_dir(Path(d), "openinterest"):
            cid = _register(meta, [r.timestamp.date() for r in rows])
            for row in rows:
                per_dir_oi[cid].append(open_interest_observation(cid, row, ingestion_time=retrieval_timestamp))
        raw_oi_dicts.append(dict(per_dir_oi))

    for symbol, path in equity_files.items():
        lines = [line for line in Path(path).read_text().splitlines() if line.strip()]
        bars = [parse_lean_equity_row(line) for line in lines]
        for bar in bars:
            underlying[symbol].extend(underlying_observations(symbol, bar, ingestion_time=retrieval_timestamp))

    quotes, quote_conflicts = merged_quotes_by_contract(*raw_quote_dicts) if raw_quote_dicts else ({}, [])
    trades, trade_conflicts = merged_quotes_by_contract(*raw_trade_dicts) if raw_trade_dicts else ({}, [])
    oi, oi_conflicts = merged_quotes_by_contract(*raw_oi_dicts) if raw_oi_dicts else ({}, [])
    all_conflicts = quote_conflicts + trade_conflicts + oi_conflicts

    lifecycles: dict = {}
    for cid, meta_fields in contract_meta_seen.items():
        underlying_symbol, right, strike, expiration, option_style = meta_fields
        from src.options.phase26_lean_sample_parser import LeanContractFileMeta
        meta = LeanContractFileMeta(underlying_symbol, right, strike, expiration, "quote", option_style, None)
        dates = observed_dates_by_contract[cid]
        if dates:
            lifecycles[cid] = build_contract_lifecycle(meta, dates, provenance, today=today)

    store = InMemoryLeanSampleStore(
        contracts=contracts, lifecycles=lifecycles, quotes=quotes, trades=trades,
        open_interest=oi, underlying=dict(underlying),
    )
    return store, all_conflicts
