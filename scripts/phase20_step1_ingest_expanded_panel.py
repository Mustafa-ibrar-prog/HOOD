#!/usr/bin/env python3
"""Phase 20, STEP 1 — combines Phase 19's real 24-contract panel with
Phase 20's real 96-contract expansion (see
logs/research_data/phase19_options_price_panel.json and
logs/research_data/phase20_options_price_panel.json, both built from
real `get_option_instruments`/`get_option_historicals` MCP probes) into
ONE 120-contract, 12-underlying, multi-expiration research panel.

Persists contracts via `OptionsDataStore` (Phase 18's real path, one
underlying at a time -- merging every expiration's contracts for that
underlying into a single save_contracts() call) and writes a fully
enriched research panel (option OHLC, underlying reference, moneyness,
DTE, forward returns, existence state, eligibility, sector, and the
mechanical-baseline/derived features the replication campaign needs) to
logs/research_data/phase20_research_panel.jsonl.

No alpha statistic is computed here. No hypothesis is tested here.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.store import HistoricalDataStore  # noqa: E402
from src.features import FeatureEngine  # noqa: E402
from src.features.volatility import RealizedVolatility  # noqa: E402
from src.options.contract_existence import ContractExistenceEvidence, classify_existence  # noqa: E402
from src.options.instrument import OptionContract  # noqa: E402
from src.options.price_history import STANDARD_FORWARD_HORIZONS, OptionPriceBar  # noqa: E402
from src.options.quality import find_suspicious_flat_price_run  # noqa: E402
from src.options.research_eligibility import OptionContractCandidate  # noqa: E402
from src.options.research_observation import build_research_series  # noqa: E402
from src.options.store import OptionsDataStore  # noqa: E402
from src.options.universe import phase20_verified_underlying_universe  # noqa: E402
from src.research.targets import future_return  # noqa: E402

PANEL_SOURCES = [
    Path("logs/research_data/phase19_options_price_panel.json"),
    Path("logs/research_data/phase20_options_price_panel.json"),
]
RESEARCH_PANEL_OUT = Path("logs/research_data/phase20_research_panel.jsonl")
VOL_WINDOW = 20
PRIMARY_HORIZON = 5
FLAT_RUN_MIN_LENGTH = 10
MIN_EXPECTED_BAR_COUNT = 50  # data-completeness threshold (Part 8) -- well below every real contract's actual 74-77 bars this phase gathered


def _underlying_closes(store: HistoricalDataStore, symbol: str) -> dict[date, float]:
    bars = store.load(symbol, "day")
    return {b.timestamp.date(): b.close for b in bars}


def main() -> None:
    universe = phase20_verified_underlying_universe()
    sector_by_symbol = {m.symbol: m.sector for m in universe.members}

    raw_contracts: list[dict] = []
    for src_path in PANEL_SOURCES:
        if not src_path.is_file():
            raise SystemExit(f"{src_path} not found -- run the real MCP data-gathering step first.")
        raw = json.loads(src_path.read_text())
        print(f"Loaded {src_path.name}: source={raw['source']!r} contracts={raw['contract_count']}", flush=True)
        raw_contracts.extend(raw["contracts"])
    print(f"Combined: {len(raw_contracts)} real contracts across {len({c['underlying_symbol'] for c in raw_contracts})} underlyings\n", flush=True)

    options_store = OptionsDataStore(Path("logs/research_data/options"))
    equity_store = HistoricalDataStore(Path("logs/research_data"))

    underlying_closes = {sym: _underlying_closes(equity_store, sym) for sym in universe.symbols}
    engine = FeatureEngine([RealizedVolatility(VOL_WINDOW)])
    underlying_derived: dict[str, dict[date, dict]] = {}
    for sym in universe.symbols:
        bars = equity_store.load(sym, "day")
        frame = engine.compute(bars)
        raw_vol = frame.columns[f"realized_vol_{VOL_WINDOW}"]
        lagged_vol = [None] + list(raw_vol[:-1])
        daily_returns = [None] + [
            (bars[i].close - bars[i - 1].close) / bars[i - 1].close if bars[i - 1].close else None for i in range(1, len(bars))
        ]
        fwd = future_return(bars, PRIMARY_HORIZON)
        by_date = {}
        for i, b in enumerate(bars):
            by_date[b.timestamp.date()] = {
                "underlying_lagged_realized_vol": lagged_vol[i],
                "underlying_daily_return": daily_returns[i],
                f"underlying_forward_return_{PRIMARY_HORIZON}": fwd[i],
            }
        underlying_derived[sym] = by_date
        print(f"  underlying-derived features built for {sym}: {len(by_date)} days", flush=True)

    contracts_by_underlying: dict[str, list[OptionContract]] = defaultdict(list)
    all_rows: list[dict] = []
    dropped_no_underlying_close = 0

    for c in raw_contracts:
        contract = OptionContract(
            underlying_symbol=c["underlying_symbol"], option_id=c["option_id"], call_put=c["call_put"],
            strike=float(c["strike"]), expiration=date.fromisoformat(c["expiration"]), contract_multiplier=int(c["multiplier"]),
            source="mcp__HOOD__get_option_instruments+get_option_historicals",
        )
        contracts_by_underlying[contract.underlying_symbol].append(contract)

        option_bars = [OptionPriceBar(date=date.fromisoformat(b["date"]), open=b["open"], high=b["high"], low=b["low"], close=b["close"]) for b in c["bars"]]
        before = len(option_bars)
        series = build_research_series(
            contract=contract, option_bars=option_bars, underlying_closes_by_date=underlying_closes[contract.underlying_symbol],
            horizons=STANDARD_FORWARD_HORIZONS,
        )
        dropped_no_underlying_close += before - len(series)

        closes = [b.close for b in option_bars]
        flat_issues = find_suspicious_flat_price_run(closes, min_run_length=FLAT_RUN_MIN_LENGTH, flat_value=0.01)
        flagged_indices: set[int] = set()
        run_start = None
        for i, cl in enumerate(closes):
            if cl == 0.01:
                if run_start is None:
                    run_start = i
            else:
                if run_start is not None and i - run_start >= FLAT_RUN_MIN_LENGTH:
                    flagged_indices.update(range(run_start, i))
                run_start = None
        if run_start is not None and len(closes) - run_start >= FLAT_RUN_MIN_LENGTH:
            flagged_indices.update(range(run_start, len(closes)))

        evidence = ContractExistenceEvidence(contract=contract, first_listed_date=None, expiration=contract.expiration, source=contract.source)
        candidate = OptionContractCandidate(
            contract=contract, bar_count=len(option_bars), min_expected_bar_count=MIN_EXPECTED_BAR_COUNT,
            existence_state=classify_existence(evidence, as_of=datetime(option_bars[0].date.year, option_bars[0].date.month, option_bars[0].date.day, tzinfo=timezone.utc)) if option_bars else None,
        )
        eligibility = candidate.evaluate() if option_bars else None

        by_date_prices = {b.date: i for i, b in enumerate(option_bars)}
        for obs in series:
            i = by_date_prices[obs.observation_date]
            underlying_feats = underlying_derived.get(contract.underlying_symbol, {}).get(obs.observation_date, {})
            option_daily_return = None
            if i > 0 and closes[i - 1] > 0:
                option_daily_return = (closes[i] - closes[i - 1]) / closes[i - 1]
            row = {
                "timestamp": obs.observation_date.isoformat(),
                "option_id": contract.option_id,
                "underlying_symbol": contract.underlying_symbol,
                "sector": sector_by_symbol.get(contract.underlying_symbol),
                "call_put": contract.call_put,
                "call_put_numeric": 1.0 if contract.call_put == "call" else 0.0,
                "strike": contract.strike,
                "expiration": contract.expiration.isoformat(),
                "option_open": obs.option_bar.open,
                "option_high": obs.option_bar.high,
                "option_low": obs.option_bar.low,
                "option_close": obs.option_bar.close,
                "underlying_close": obs.underlying_close,
                "dte": obs.dte,
                "dte_bucket": obs.dte_bucket.value,
                "log_moneyness": obs.moneyness.log_moneyness_value,
                "moneyness_ratio": obs.moneyness.moneyness_ratio_value,
                "moneyness_bucket": obs.moneyness.bucket.value,
                "moneyness_x_dte_interaction": obs.moneyness.log_moneyness_value * obs.dte,
                "option_daily_return": option_daily_return,
                "abs_option_daily_return": abs(option_daily_return) if option_daily_return is not None else None,
                "is_flat_pinned": 1.0 if i in flagged_indices else 0.0,
                "existence_state": eligibility.existence_state.value if eligibility else None,
                "is_research_eligible": eligibility.is_eligible if eligibility else False,
                **{f"forward_return_{h}": obs.forward_returns.get(h) for h in STANDARD_FORWARD_HORIZONS},
                **underlying_feats,
            }
            if row.get(f"forward_return_{PRIMARY_HORIZON}") is not None:
                r = row[f"forward_return_{PRIMARY_HORIZON}"]
                row[f"abs_forward_return_{PRIMARY_HORIZON}"] = abs(r)
            all_rows.append(row)

    for sym, contracts in contracts_by_underlying.items():
        options_store.save_contracts(sym, contracts)
        print(f"  persisted {len(contracts)} contracts for {sym} via OptionsDataStore.save_contracts()", flush=True)

    RESEARCH_PANEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    with RESEARCH_PANEL_OUT.open("w") as fh:
        for row in all_rows:
            fh.write(json.dumps(row, sort_keys=True))
            fh.write("\n")

    print(f"\nWrote {len(all_rows)} research rows to {RESEARCH_PANEL_OUT} "
          f"({dropped_no_underlying_close} option bars dropped for missing underlying close -- never fabricated).", flush=True)
    print(f"Underlyings: {len(contracts_by_underlying)}  Contracts: {sum(len(v) for v in contracts_by_underlying.values())}  "
          f"Expirations: {sorted({c['expiration'] for c in raw_contracts})}  Horizons: {STANDARD_FORWARD_HORIZONS}", flush=True)
    print("\nSTEP 1 COMPLETE — real data transcribed and enriched, no alpha computed.", flush=True)


if __name__ == "__main__":
    main()
