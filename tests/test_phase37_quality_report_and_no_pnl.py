"""Phase 37, Part 15/19 — the data-quality report (never alpha evidence)
and the explicit absence of any simulated P&L anywhere in this package.
"""

from __future__ import annotations

import ast
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config.settings import Settings
from src.market.data_provider import MarketDataProvider
from src.research_recorder.quality_report import build_data_quality_report
from src.research_recorder.recorder import RecorderStores, run_observation_cycle
from src.research_recorder.storage import CycleLogStore, NormalizedOptionStore, NormalizedUnderlyingStore, RawObservationStore, ResearchSignalStore

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "src/research_recorder"
NOW = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)


class FakeClient:
    def get_equity_quotes(self, symbols):
        return {"data": {"results": [{
            "quote": {"symbol": symbols[0], "bid_price": None, "ask_price": None, "last_trade_price": "230.0", "venue_last_trade_time": NOW.isoformat()},
            "close": {"price": "228.0"},
        }]}}

    def get_option_quotes(self, instrument_ids):
        results = [{"quote": {"instrument_id": oid, "bid_price": "1.0", "ask_price": "1.05", "volume": "100", "open_interest": "200", "updated_at": NOW.isoformat()}} for oid in instrument_ids]
        return {"data": {"results": results}}


class FakeMarket(MarketDataProvider):
    def get_market_snapshot(self, option_id, underlying_symbol, now=None):
        raise NotImplementedError

    def get_underlying_snapshot(self, symbol, now=None):
        raise NotImplementedError

    def get_option_expirations(self, underlying_symbol):
        return [(NOW.date() + timedelta(days=30))]

    def get_option_chain_candidates(self, underlying_symbol, **filters):
        return [
            {"id": f"opt-{underlying_symbol}-{strike}", "type": "call" if strike < 240 else "put", "strike_price": str(strike),
             "expiration_date": (NOW.date() + timedelta(days=30)).isoformat(), "state": "active", "tradability": "tradable"}
            for strike in (220, 230, 240)
        ]


def _stores(tmp_path):
    return RecorderStores(
        raw=RawObservationStore(tmp_path / "raw.jsonl"), underlying=NormalizedUnderlyingStore(tmp_path / "u.jsonl"),
        option=NormalizedOptionStore(tmp_path / "o.jsonl"), signal=ResearchSignalStore(tmp_path / "s.jsonl"),
        cycle_log=CycleLogStore(tmp_path / "c.jsonl"),
    )


def test_quality_report_reflects_real_recorded_data():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        settings = Settings.from_env(env={"TRADING_MODE": "paper"})
        run_observation_cycle(client=FakeClient(), market=FakeMarket(), settings=settings, stores=stores, now=NOW, universe=["AAPL"])
        report = build_data_quality_report(stores)

        assert report.cycles_attempted == 1
        assert report.cycles_successful == 1
        assert report.cycles_failed == 0
        assert report.symbols_attempted == 1
        assert report.option_contracts_observed == 3
        assert report.unique_option_contracts == 3
        assert report.quote_completeness_pct == 1.0
        assert report.calls == 2 and report.puts == 1


def test_report_is_never_treated_as_alpha_evidence():
    """No field on DataQualityReport suggests a trading signal -- this is
    a data-quality report, never alpha evidence (Part 19's explicit
    instruction)."""
    import dataclasses

    from src.research_recorder.quality_report import DataQualityReport

    field_names = {f.name for f in dataclasses.fields(DataQualityReport)}
    for forbidden in ("edge", "alpha", "expectancy", "profit", "win_rate", "sharpe", "signal_score"):
        assert not any(forbidden in name for name in field_names), field_names


def test_empty_stores_produce_a_report_with_no_crash():
    with tempfile.TemporaryDirectory() as d:
        report = build_data_quality_report(_stores(Path(d)))
        assert report.cycles_attempted == 0
        assert report.option_contracts_observed == 0
        assert report.quote_completeness_pct is None


# --- No simulated P&L, anywhere in this package -------------------------------------------------


def test_no_file_in_the_package_computes_a_simulated_pnl_or_fill():
    forbidden_substrings = (
        "simulated_entry", "simulated_fill", "simulated_exit", "simulated_profit", "simulated_loss",
        "paper_account_balance", "unrealized_pnl", "realized_pnl", "SimulatedFill",
    )
    for path in PACKAGE_DIR.rglob("*.py"):
        source = path.read_text()
        for forbidden in forbidden_substrings:
            assert forbidden not in source, f"{path} contains {forbidden!r}"


def test_no_dataclass_in_the_package_has_a_pnl_shaped_field():
    """Structural check across every dataclass field name defined in the
    package -- catches a P&L-shaped field even if named something the
    substring check above didn't anticipate."""
    # Deliberately excludes bare "profit"/"loss" -- this package legitimately
    # records Robinhood's own `chance_of_profit_long`/`chance_of_profit_short`
    # descriptive analytics fields (Part 7's explicit instruction), which are
    # not a simulated P&L calculation. The substring test above already
    # checks the specific simulated_profit/simulated_loss phrases precisely.
    forbidden_tokens = ("pnl", "balance", "fill_price", "entry_price", "exit_price")
    for path in PACKAGE_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        name = item.target.id.lower()
                        for token in forbidden_tokens:
                            assert token not in name, f"{path}::{node.name}.{item.target.id} looks P&L-shaped"


def test_no_file_imports_a_paper_trading_or_backtest_pnl_module():
    forbidden_prefixes = ("src.position_manager.store", "src.backtesting.portfolio", "src.backtesting.metrics")
    for path in PACKAGE_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in forbidden_prefixes:
                    assert not node.module.startswith(prefix), f"{path} imports {node.module}"
