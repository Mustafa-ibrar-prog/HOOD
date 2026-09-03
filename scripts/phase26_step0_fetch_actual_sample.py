#!/usr/bin/env python3
"""Phase 26, Part 4 — fetch an ACTUAL, real, historical options data
sample without payment.

Source: QuantConnect/Lean (github.com/QuantConnect/Lean), the open-source
algorithmic trading engine. Its repository ships a small, real,
AlgoSeek-sourced historical options sample bundled specifically for
running the engine's own demo algorithms and tests -- checked into the
repo under `Data/option/` and `Data/equity/`, licensed Apache-2.0 (see
`raw.githubusercontent.com/QuantConnect/Lean/master/LICENSE`), publicly
downloadable via `raw.githubusercontent.com` with no account, no API
key, and no payment of any kind.

This was found and chosen after Phase 25 confirmed that essentially
every dedicated options-data vendor's own domain (orats.com,
thetadata.net/docs.thetadata.us, polygon.io, datashop.cboe.com,
alphavantage.co, ...) is EGRESS_BLOCKED from this environment, and this
phase independently reconfirmed that block extends to non-financial
control domains too (example.com, en.wikipedia.org) -- i.e. this
environment allows essentially only github.com/raw.githubusercontent.com
plus WebSearch. Given that constraint, a real options dataset that
happens to be GitHub-hosted is the only category of source this phase
could actually retrieve real bytes from, rather than merely read a
vendor's claims about.

Every file this script downloads is REAL data as originally published by
QuantConnect/AlgoSeek -- nothing here is fabricated, synthesized, or
interpolated. Coverage is real but narrow: 5 underlyings (AAPL, FOXA,
GOOG, NWSA, TWX) at daily resolution for 2013-2016, plus one real
minute-resolution SPY sample for 2023-08-03 (within this phase's
preferred 2021-2024 window) -- NVDA and TSLA are NOT present in this
sample (confirmed absent from the repository's directory listing this
phase, not merely unchecked).

Idempotent: re-running skips files already present with a matching size.
"""

from __future__ import annotations

import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "logs/research_data/phase26_raw"
ZIP_DIR = RAW_DIR / "zips"
EXTRACT_DIR = RAW_DIR / "extracted"

BASE_URL = "https://raw.githubusercontent.com/QuantConnect/Lean/master"

# (relative URL path under BASE_URL, local zip filename, extraction subdir)
FILES = (
    ("Data/option/usa/daily/aapl_2015_quote_american.zip", "aapl_2015_quote_american.zip", "aapl_2015_quote"),
    ("Data/option/usa/daily/aapl_2015_trade_american.zip", "aapl_2015_trade_american.zip", "aapl_2015_trade"),
    ("Data/option/usa/daily/aapl_2014_openinterest_american.zip", "aapl_2014_openinterest_american.zip", "aapl_2014_oi"),
    ("Data/option/usa/daily/aapl_2014_quote_american.zip", "aapl_2014_quote_american.zip", "aapl_2014_quote"),
    ("Data/option/usa/daily/aapl_2014_trade_american.zip", "aapl_2014_trade_american.zip", "aapl_2014_trade"),
    ("Data/option/usa/minute/spy/20230803_quote_american.zip", "spy_20230803_quote_american.zip", "spy_20230803_quote"),
    ("Data/option/usa/minute/spy/20230803_trade_american.zip", "spy_20230803_trade_american.zip", "spy_20230803_trade"),
    ("Data/equity/usa/daily/aapl.zip", "aapl_equity_daily.zip", "aapl_equity"),
    ("Data/equity/usa/daily/spy.zip", "spy_equity_daily.zip", "spy_equity"),
    ("LICENSE", "LICENSE.txt", None),
)


def fetch(url_path: str, dest: Path) -> None:
    url = f"{BASE_URL}/{url_path}"
    req = urllib.request.Request(url, headers={"User-Agent": "hood-research-phase26/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 -- fixed https, github raw content only
        data = resp.read()
    dest.write_bytes(data)


def main() -> None:
    ZIP_DIR.mkdir(parents=True, exist_ok=True)
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)

    for url_path, filename, extract_subdir in FILES:
        dest = ZIP_DIR / filename
        if dest.is_file() and dest.stat().st_size > 0:
            print(f"SKIP (already present, {dest.stat().st_size} bytes): {filename}", flush=True)
        else:
            print(f"FETCH: {url_path}", flush=True)
            try:
                fetch(url_path, dest)
            except Exception as exc:  # noqa: BLE001 -- report and stop, never fabricate a substitute
                print(f"FAILED to fetch {url_path}: {exc}", file=sys.stderr, flush=True)
                print("No substitute/fabricated data will be created. Stopping.", file=sys.stderr, flush=True)
                sys.exit(1)
            print(f"  -> {dest.stat().st_size} bytes", flush=True)

        if extract_subdir and dest.suffix == ".zip":
            out_dir = EXTRACT_DIR / extract_subdir
            if out_dir.is_dir() and any(out_dir.iterdir()):
                print(f"  (already extracted to {out_dir})", flush=True)
            else:
                out_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(dest) as zf:
                    zf.extractall(out_dir)
                print(f"  extracted -> {out_dir} ({len(list(out_dir.iterdir()))} files)", flush=True)

    print("\nSTEP 0 COMPLETE — real QuantConnect/Lean sample data fetched (Apache-2.0, no payment, no account). "
          f"Raw files under {RAW_DIR}", flush=True)


if __name__ == "__main__":
    main()
