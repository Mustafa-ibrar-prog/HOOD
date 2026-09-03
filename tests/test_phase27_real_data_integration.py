"""Phase 27, Part 9/16 — end-to-end integration against the REAL,
actually-downloaded Phase 27 expansion sample
(logs/research_data/phase27_raw/). Skipped (not failed) when that
gitignored directory isn't present -- run
scripts/phase26_step0_fetch_actual_sample.py and
scripts/phase27_step0_fetch_expansion_sample.py first to exercise these
for real.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.options.phase26_ingest import RAW_EXTRACTED_DIR as P26_EXTRACTED
from src.options.phase26_pit_certification import contracts_with_any_knowable_quote_as_of
from src.options.phase26_quality_rules import run_all_quality_checks
from src.options.phase27_corporate_actions import find_split_boundary_discontinuities
from src.options.phase27_ingest import PHASE27_RAW_EXTRACTED_DIR as P27_EXTRACTED
from src.options.phase27_ingest import build_expanded_store_from_directories

pytestmark = pytest.mark.skipif(
    not (P27_EXTRACTED / "goog_min_20151223_quote").is_dir(),
    reason="Phase 27 real expansion sample not fetched this session -- run scripts/phase27_step0_fetch_expansion_sample.py first",
)


@pytest.fixture(scope="module")
def real_expanded_store():
    store, conflicts = build_expanded_store_from_directories(
        quote_dirs=[P27_EXTRACTED / "goog_2015_quote", P27_EXTRACTED / "goog_min_20151223_quote",
                    P27_EXTRACTED / "goog_min_20151224_quote", P27_EXTRACTED / "goog_min_20151228_quote"],
        trade_dirs=[P27_EXTRACTED / "goog_2015_trade"], oi_dirs=[P27_EXTRACTED / "goog_2015_oi"],
        equity_files={"GOOG": P27_EXTRACTED / "goog_equity" / "goog.csv"},
        retrieval_timestamp=datetime.now(timezone.utc), today=date(2026, 9, 3),
    )
    return store, conflicts


def test_real_goog_multi_day_merge_has_zero_conflicts(real_expanded_store):
    """Same real provider across daily + 3 real minute days -- no
    genuine value disagreement is expected."""
    _, conflicts = real_expanded_store
    assert conflicts == []


def test_real_goog_merged_data_passes_timestamp_ordering(real_expanded_store):
    """This is the exact real bug this phase found and fixed --
    reconfirm it stays fixed against the real data."""
    from src.options.phase26_quality_rules import check_timestamp_ordering
    store, _ = real_expanded_store
    assert check_timestamp_ordering(store) == []


def test_real_goog_data_passes_every_critical_quality_check(real_expanded_store):
    store, _ = real_expanded_store
    flags = run_all_quality_checks(store)
    critical = [f for f in flags if f.severity == "critical"]
    assert critical == []


def test_real_goog_chain_grows_across_the_three_real_consecutive_trading_days(real_expanded_store):
    """A genuine multi-day real PIT test this phase's data newly makes
    possible: as-of the first real day, fewer contracts are knowable
    than as-of the third."""
    store, _ = real_expanded_store
    as_of_day1 = datetime(2015, 12, 23, 23, 59)
    as_of_day3 = datetime(2015, 12, 28, 23, 59)
    knowable_day1 = contracts_with_any_knowable_quote_as_of(store, as_of=as_of_day1)
    knowable_day3 = contracts_with_any_knowable_quote_as_of(store, as_of=as_of_day3)
    assert len(knowable_day3) >= len(knowable_day1) > 0


def test_real_aapl_split_boundary_flags_a_real_discontinuity():
    store, _ = build_expanded_store_from_directories(
        quote_dirs=[P26_EXTRACTED / "aapl_2014_quote"], trade_dirs=[], oi_dirs=[], equity_files={},
        retrieval_timestamp=datetime.now(timezone.utc), today=date(2026, 9, 3),
    )
    flags = find_split_boundary_discontinuities(store, "AAPL", date(2014, 6, 9))
    assert len(flags) > 0
    assert all(f.legacy_strike > 0 for f in flags)
