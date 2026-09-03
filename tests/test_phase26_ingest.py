"""Phase 26, Part 12/15 — the filesystem loader, tested against small,
self-contained synthetic CSV files (real format, not real market values)
so this test never depends on the gitignored, session-fetched raw data
directory."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.options.phase26_ingest import build_store_from_directories


def _write(path, name, content):
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(content)


def test_loader_builds_a_contract_from_a_synthetic_quote_file(tmp_path):
    quote_dir = tmp_path / "quotes"
    _write(quote_dir, "aapl_quote_american_call_1000000_20160115.csv",
           "20150102 00:00,181000,186000,162000,175500,224,183500,203500,167000,177500,103\n"
           "20150105 00:00,175500,175500,153500,159000,10,177500,177500,154000,160500,601\n")

    store = build_store_from_directories(
        quote_dirs=[quote_dir], trade_dirs=[], oi_dirs=[], equity_files={},
        retrieval_timestamp=datetime.now(timezone.utc), today=date(2026, 9, 3),
    )
    cid = "AAPL_call_100.0000_2016-01-15"
    assert cid in store.contracts
    assert len(store.quotes[cid]) == 2 * 10  # 10 fields per real row
    lc = store.lifecycles[cid]
    assert lc.first_observable_date == date(2015, 1, 2)
    assert lc.last_trade_date == date(2015, 1, 5)


def test_loader_merges_quote_and_trade_for_the_same_contract(tmp_path):
    quote_dir, trade_dir = tmp_path / "q", tmp_path / "t"
    _write(quote_dir, "aapl_quote_american_call_1000000_20160115.csv",
           "20150102 00:00,181000,186000,162000,175500,224,183500,203500,167000,177500,103\n")
    _write(trade_dir, "aapl_trade_american_call_1000000_20160115.csv",
           "20150102 00:00,175000,180000,170000,176000,50\n")

    store = build_store_from_directories(
        quote_dirs=[quote_dir], trade_dirs=[trade_dir], oi_dirs=[], equity_files={},
        retrieval_timestamp=datetime.now(timezone.utc), today=date(2026, 9, 3),
    )
    cid = "AAPL_call_100.0000_2016-01-15"
    assert cid in store.contracts
    assert len(store.quotes[cid]) > 0
    assert len(store.trades[cid]) > 0
    lc = store.lifecycles[cid]
    # lifecycle should span BOTH quote and trade observed dates
    assert lc.first_observable_date == date(2015, 1, 2)


def test_loader_builds_underlying_observations_from_an_equity_file(tmp_path):
    eq_dir = tmp_path / "eq"
    eq_dir.mkdir()
    (eq_dir / "aapl.csv").write_text("20150102 00:00,1114100,1114400,1073500,1093300,52381530\n")

    store = build_store_from_directories(
        quote_dirs=[], trade_dirs=[], oi_dirs=[], equity_files={"AAPL": eq_dir / "aapl.csv"},
        retrieval_timestamp=datetime.now(timezone.utc), today=date(2026, 9, 3),
    )
    closes = [o.value for o in store.underlying["AAPL"] if o.field == "close"]
    assert closes == [109.33]


def test_loader_is_a_no_op_for_empty_directory_lists(tmp_path):
    store = build_store_from_directories(
        quote_dirs=[], trade_dirs=[], oi_dirs=[], equity_files={},
        retrieval_timestamp=datetime.now(timezone.utc), today=date(2026, 9, 3),
    )
    assert store.contracts == {}
    assert store.quotes == {}
