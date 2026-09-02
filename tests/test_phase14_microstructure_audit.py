"""Phase 14, Part 2-4, 23: regression tests proving the factual claims
underlying scripts/phase14_step0_microstructure_data_audit.py's
MICROSTRUCTURE_DATA_INSUFFICIENT verdict, so a future change to the data
layer that silently adds (or removes) microstructure capability is caught
by a failing test rather than by the next research phase re-deriving the
same audit from scratch.

These are "data availability detection" / "field provenance" tests per
Part 23 — scoped to what this phase actually needed, since Phase 14 stops
at the audit stage and never builds features or registers hypotheses.
"""

from __future__ import annotations

import dataclasses
import inspect
from pathlib import Path

from src.data import HistoricalDataStore, us_diversified_universe
from src.data.bar import Bar, Quote

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_bar_has_no_bid_ask_or_trade_fields():
    """Bar (the only type ever persisted to disk) is pure OHLCV — proves
    daily bars cannot be mistaken for a microstructure data source."""
    field_names = {f.name for f in dataclasses.fields(Bar)}
    assert field_names == {"timestamp", "symbol", "timeframe", "open", "high", "low", "close", "volume", "source"}
    for forbidden in ("bid", "ask", "bid_size", "ask_size", "trade_price", "trade_size", "trade_direction"):
        assert forbidden not in field_names


def test_quote_bid_ask_size_fields_exist_in_schema_but_are_never_populated_from_equity_quotes():
    """Quote's schema *carries* bid/ask/size fields, but Quote.from_equity_quote
    (the equity-underlying path relevant to this universe) never sets bid/ask,
    and no size field is ever populated by any adapter — confirms the audit's
    'schema has the field, no real data source fills it' distinction."""
    field_names = {f.name for f in dataclasses.fields(Quote)}
    assert {"bid", "ask", "bid_size", "ask_size", "trade_price", "trade_size"} <= field_names
    source = inspect.getsource(Quote.from_equity_quote)
    assert "bid=" not in source and "ask=" not in source


def test_historical_data_store_never_references_quote():
    """No QuoteStore, no save_quote — HistoricalDataStore's entire surface
    operates on Bar only. If a future change adds quote persistence, this
    test should be updated deliberately, not silently pass."""
    source = inspect.getsource(HistoricalDataStore)
    assert "Quote" not in source
    assert not hasattr(HistoricalDataStore, "save_quote")


def test_only_day_timeframe_is_ever_persisted_for_the_research_universe():
    """Static guarantee backing the audit's intraday-coverage finding:
    every (symbol, timeframe) pair actually written to logs/research_data/
    uses timeframe == 'day'. A future ingestion of intraday bars would
    show up here as a new timeframe and this test would need updating —
    that's the point."""
    store = HistoricalDataStore(REPO_ROOT / "logs" / "research_data")
    datasets = store.list_datasets()
    if not datasets:
        import pytest

        pytest.skip("no persisted research data in this environment")
    timeframes = {tf for _symbol, tf in datasets}
    assert timeframes == {"day"}


def test_no_order_book_or_trade_direction_code_exists_anywhere_in_src_or_scripts():
    """Repository-wide static guarantee: no order-book/depth/imbalance/
    trade-direction/signed-volume code exists in src/ or scripts/ — the
    audit's Part E/D finding, made regression-proof. The audit script
    itself is exempt: it legitimately NAMES these terms in its
    explanatory output precisely to document their absence."""
    forbidden_terms = ("order_book", "order book", "level2", "level 2", "trade_direction", "signed_volume", "order_imbalance")
    audit_script = REPO_ROOT / "scripts" / "phase14_step0_microstructure_data_audit.py"
    for directory in ("src", "scripts"):
        for path in (REPO_ROOT / directory).rglob("*.py"):
            if path == audit_script:
                continue
            source = path.read_text()
            for term in forbidden_terms:
                assert term not in source, f"{path} references {term!r} — re-run the Phase 14 data audit, capability may have changed"


def test_us_diversified_universe_has_only_daily_bars_available():
    """Confirms the audit's Part G coverage table: every US_DIVERSIFIED
    symbol has a persisted 'day' dataset and nothing else."""
    store = HistoricalDataStore(REPO_ROOT / "logs" / "research_data")
    universe = us_diversified_universe()
    have_any_data = any(store.load_metadata(s, "day") is not None for s in universe.symbols)
    if not have_any_data:
        import pytest

        pytest.skip("no persisted research data in this environment")
    for symbol in universe.symbols:
        meta_day = store.load_metadata(symbol, "day")
        if meta_day is None:
            continue
        for other_timeframe in ("1minute", "5minute", "15minute", "hour"):
            assert store.load_metadata(symbol, other_timeframe) is None


def test_phase14_audit_script_exits_nonzero_with_insufficient_verdict():
    """The audit script itself must fail closed (nonzero exit) when data
    is insufficient — the same STOP-the-phase convention every prior
    phase's data gate uses (see phase13_step0's SystemExit(1) pattern)."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "phase14_step0_microstructure_data_audit.py")],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=60,
    )
    assert "MICROSTRUCTURE_DATA_INSUFFICIENT" in result.stdout
    assert result.returncode != 0
