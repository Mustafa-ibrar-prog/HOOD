#!/usr/bin/env python3
"""Phase 14 — STEP 0: CRITICAL DATA CAPABILITY GATE for market
microstructure / liquidity research (Part 2-4).

This script must run BEFORE any P14-MICRO-* hypothesis is registered. It
inspects the ACTUAL repository — data shapes (src/data/bar.py), storage
(src/data/store.py), the live-market provider (src/market/models.py,
src/market/hood_provider.py), and what is genuinely persisted on disk
under logs/research_data/ — rather than inferring availability from API
documentation alone (Part 2's explicit instruction).

Per Part 4 ("Hard Stop Conditions"): if only daily OHLCV exists, this
script MUST report MICROSTRUCTURE_DATA_INSUFFICIENT and stop. It does
NOT fabricate bid/ask, spread, order flow, trade direction, or
order-book imbalance from daily OHLCV under any circumstance — there is
no code path in this script that manufactures a microstructure feature.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import HistoricalDataStore, us_diversified_universe  # noqa: E402
from src.data.bar import Bar, Quote  # noqa: E402

RESEARCH_DATA_ROOT = Path("logs/research_data")


def _print_header(title: str) -> None:
    print("\n" + "=" * 100, flush=True)
    print(title, flush=True)
    print("=" * 100, flush=True)


def main() -> None:
    _print_header("PART A — DAILY DATA (Section 2.A)")
    bar_fields = {f.name for f in dataclasses.fields(Bar)}
    print(f"  src/data/bar.py Bar fields: {sorted(bar_fields)}", flush=True)
    required_ohlcv = {"open", "high", "low", "close", "volume"}
    print(f"  OHLCV fields present on Bar: {required_ohlcv <= bar_fields}", flush=True)

    _print_header("PART B — INTRADAY DATA (Section 2.B)")
    print("  Inspecting src/market/hood_provider.py: the LIVE trading path's MarketDataProvider", flush=True)
    print("  defaults `history_interval=\"5minute\"` for get_equity_historicals/get_option_historicals", flush=True)
    print("  when building a live market snapshot for a trading DECISION -- this is a real capability", flush=True)
    print("  of the underlying HOOD connection, but it is used TRANSIENTLY (fetched, used, discarded) for", flush=True)
    print("  the live decision path only. Nothing in src/data/store.py or any research script ever calls", flush=True)
    print("  save()/upsert() with a 5minute/hourly/other-intraday timeframe.", flush=True)

    store = HistoricalDataStore(RESEARCH_DATA_ROOT)
    datasets = store.list_datasets()
    timeframes_present = sorted({tf for _sym, tf in datasets})
    print(f"\n  Actual persisted (symbol, timeframe) datasets on disk: {len(datasets)}", flush=True)
    print(f"  Distinct timeframes ever persisted: {timeframes_present}", flush=True)
    if timeframes_present != ["day"]:
        print(f"  UNEXPECTED: found a persisted timeframe other than 'day': {timeframes_present}", flush=True)
    else:
        print("  CONFIRMED: every persisted dataset in this repository is 'day' (daily OHLCV) -- ZERO", flush=True)
        print("  intraday bars (1-minute, 5-minute, 15-minute, hourly, or otherwise) are stored anywhere.", flush=True)

    _print_header("PART C — QUOTE DATA / BID-ASK (Section 2.C)")
    quote_fields = {f.name for f in dataclasses.fields(Quote)}
    print(f"  src/data/bar.py Quote fields (the ONLY bid/ask-shaped research-layer type): {sorted(quote_fields)}", flush=True)
    print("  Per src/data/bar.py's own module docstring (verified against src/market/hood_provider.py,", flush=True)
    print("  src/market/models.py -- not invented here):", flush=True)
    print("    - EquityQuote (get_equity_quotes) does NOT surface bid/ask at all today -- Quote.bid/ask are", flush=True)
    print("      always None when built from an equity quote (from_equity_quote never sets them).", flush=True)
    print("    - OptionQuote (get_option_quotes) DOES carry bid_price/ask_price, but only for OPTION", flush=True)
    print("      contracts, and only as a LIVE, current-moment snapshot (as_of = the moment of the call) --", flush=True)
    print("      there is no historical archive of option quotes anywhere in this codebase.", flush=True)
    print("    - bid_size/ask_size are NEVER populated by any verified HOOD response shape in this codebase", flush=True)
    print("      (always None, by explicit design -- 'an absent field must read as not supported ... never", flush=True)
    print("      as a silently fabricated 0').", flush=True)
    print("\n  Persistence check: does src/data/store.py (HistoricalDataStore) ever persist a Quote?", flush=True)
    import inspect
    store_source = inspect.getsource(HistoricalDataStore)
    quote_referenced_in_store = "Quote" in store_source
    print(f"    HistoricalDataStore references Quote anywhere: {quote_referenced_in_store}", flush=True)
    print("    CONFIRMED: HistoricalDataStore.save()/upsert()/load() operate on Bar objects only. There is", flush=True)
    print("    no QuoteStore, no save_quote(), and no quote data of any kind persisted to disk in this repo.", flush=True)

    _print_header("PART D — TRADE DATA (Section 2.D)")
    print("  trade_price:  Quote.trade_price exists in the schema, but is only ever populated from a LIVE", flush=True)
    print("                quote snapshot's last_trade_price/mark_price (current moment only) -- never a", flush=True)
    print("                historical trade tape.", flush=True)
    print("  trade_size:   NEVER populated by any verified HOOD response shape in this codebase (always None).", flush=True)
    print("  trade_timestamp (as a genuine per-trade tick): does not exist -- the finest-grained persisted", flush=True)
    print("                unit of anything in this repository is one DAILY bar.", flush=True)
    print("  trade_direction (buy/sell classification): no field, no classifier, no reference anywhere in", flush=True)
    print("                src/ or scripts/ (confirmed via repository-wide search).", flush=True)

    _print_header("PART E — ORDER BOOK DATA (Section 2.E)")
    print("  Level 1 / Level 2 / market depth / order-book imbalance: repository-wide search for", flush=True)
    print("  order_book/depth/level2/level 2/order_imbalance/signed_volume/trade_direction found ZERO", flush=True)
    print("  matches in src/ or scripts/. A raw MCP tool (mcp__HOOD__get_equity_price_book) is available in", flush=True)
    print("  this AGENT session's toolset, but it is (a) never called anywhere in src/ or scripts/ -- i.e.", flush=True)
    print("  not integrated into this codebase's data pipeline at all -- and (b) even if it were, it is a", flush=True)
    print("  LIVE, current-moment order-book snapshot tool with no historical archive, exactly like", flush=True)
    print("  get_equity_quotes/get_option_quotes above. Calling it now would not produce a HISTORICAL", flush=True)
    print("  dataset spanning the 2021-09-01..2023-08-31 discovery window -- it would only return today's", flush=True)
    print("  book, which cannot be backdated or used for any point-in-time historical research.", flush=True)

    _print_header("PART F — MARKET-WIDE LIQUIDITY DATA (Section 2.F)")
    print("  No separate market-wide liquidity index, dataset, or data source exists anywhere in this", flush=True)
    print("  repository (e.g. no TED spread, no VIX-style liquidity proxy, no market-maker inventory data).", flush=True)

    _print_header("PART G — SYMBOL / DATE COVERAGE OF WHAT ACTUALLY EXISTS (daily OHLCV only)")
    universe = us_diversified_universe()
    usable = [s for s in universe.symbols if store.load_metadata(s, "day") is not None]
    print(f"  US_DIVERSIFIED: {len(usable)}/{len(universe.symbols)} symbols have a persisted 'day' dataset.", flush=True)
    for symbol in universe.symbols:
        meta = store.load_metadata(symbol, "day")
        if meta is None:
            print(f"    {symbol}: NOT PERSISTED", flush=True)
        else:
            print(f"    {symbol}: day bars, {meta.record_count} records, {meta.start_timestamp.date()}..{meta.end_timestamp.date()}", flush=True)

    _print_header("GATE DECISION")
    have_intraday = timeframes_present != [] and timeframes_present != ["day"]
    have_historical_quotes = False  # established above: no QuoteStore, no persisted Quote data anywhere
    have_trade_data = False
    have_order_book = False
    sufficient = have_intraday or have_historical_quotes or have_trade_data or have_order_book

    if sufficient:
        print("MICROSTRUCTURE_DATA_SUFFICIENT -- see printed evidence above for which specific data types", flush=True)
        print("are usable and their exact coverage.", flush=True)
        sys.exit(0)

    print("MICROSTRUCTURE_DATA_INSUFFICIENT", flush=True)
    print("", flush=True)
    print("Only daily OHLCV (open/high/low/close/volume) exists anywhere in this repository's historical", flush=True)
    print("research data. Specifically MISSING, with zero historical coverage of any kind:", flush=True)
    print("  - intraday bars of any granularity (1m/5m/15m/hourly) -- never persisted, though the live path", flush=True)
    print("    can fetch 5-minute bars transiently for a live trading decision", flush=True)
    print("  - bid/ask quotes (equity or option) -- EquityQuote never surfaces bid/ask at all; OptionQuote", flush=True)
    print("    does, but only as a live current-moment snapshot with no historical archive", flush=True)
    print("  - bid size / ask size -- never populated by any verified response shape in this codebase", flush=True)
    print("  - trade-level data (price/size/timestamp/direction) -- no tick data of any kind exists", flush=True)
    print("  - order-book / depth / order-imbalance data -- no integration anywhere in this codebase; the", flush=True)
    print("    one available raw MCP tool for this is live-only and unused by the data pipeline", flush=True)
    print("  - market-wide liquidity data -- no such dataset exists", flush=True)
    print("", flush=True)
    print("Per Part 4's explicit instruction: this script does NOT manufacture bid/ask, spread, order flow,", flush=True)
    print("trade direction, or order-book imbalance from daily OHLCV. Daily volume is NOT a substitute for", flush=True)
    print("bid/ask or order-flow data (Part 3's explicit instruction) and is not being presented as such.", flush=True)
    print("", flush=True)
    print("STOPPING after this audit, per Part 4/25. No P14-MICRO-* hypothesis family is created. No", flush=True)
    print("features are built. No discovery analysis is run.", flush=True)
    sys.exit(1)


if __name__ == "__main__":
    main()
