"""Phase 26, Part 4/15 — end-to-end integration against the REAL,
actually-downloaded QuantConnect/Lean sample
(logs/research_data/phase26_raw/). Skipped (not failed) when that
gitignored directory isn't present -- e.g. a fresh checkout that hasn't
run scripts/phase26_step0_fetch_actual_sample.py yet -- since this repo
never commits bulk fetched data (established convention since Phase 19).
Run the fetch script first to exercise these for real.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.options.phase26_chain_reconstruction import contracts_incorrectly_visible_before_first_observation, reconstruct_chain_as_of
from src.options.phase26_execution_realism import ExecutionRealismGrade, build_execution_realism_report
from src.options.phase26_ingest import RAW_EXTRACTED_DIR, build_store_from_directories
from src.options.phase26_quality_rules import run_all_quality_checks

pytestmark = pytest.mark.skipif(
    not (RAW_EXTRACTED_DIR / "aapl_2015_quote").is_dir(),
    reason="real sample not fetched this session -- run scripts/phase26_step0_fetch_actual_sample.py first",
)


@pytest.fixture(scope="module")
def real_store():
    return build_store_from_directories(
        quote_dirs=[RAW_EXTRACTED_DIR / "aapl_2015_quote", RAW_EXTRACTED_DIR / "spy_20230803_quote"],
        trade_dirs=[RAW_EXTRACTED_DIR / "aapl_2015_trade", RAW_EXTRACTED_DIR / "spy_20230803_trade"],
        oi_dirs=[],
        equity_files={"AAPL": RAW_EXTRACTED_DIR / "aapl_equity" / "aapl.csv"},
        retrieval_timestamp=datetime.now(timezone.utc), today=date(2026, 9, 3),
    )


def test_real_aapl_contract_ingested_with_expected_identity(real_store):
    cid = "AAPL_call_100.0000_2016-01-15"
    assert cid in real_store.contracts
    c = real_store.contracts[cid]
    assert c.underlying_symbol == "AAPL"
    assert c.call_put == "call"
    assert c.strike == 100.0


def test_real_underlying_close_matches_known_aapl_price(real_store):
    """Independent, real-world cross-check: AAPL's publicly known close
    on 2015-01-02 was $109.33."""
    close = next(o.value for o in real_store.underlying["AAPL"] if o.field == "close" and o.timestamps.event_time.date() == date(2015, 1, 2))
    assert close == pytest.approx(109.33)


def test_real_spy_contracts_ingested_for_2023(real_store):
    spy_ids = [cid for cid in real_store.contracts if cid.startswith("SPY")]
    assert len(spy_ids) == 4  # 430/470 call/put


def test_real_data_passes_every_critical_quality_check(real_store):
    flags = run_all_quality_checks(real_store)
    critical = [f for f in flags if f.severity == "critical"]
    assert critical == []


def test_real_spy_execution_realism_is_grade_a(real_store):
    for cid in real_store.contracts:
        if cid.startswith("SPY"):
            rep = build_execution_realism_report(real_store, cid)
            assert rep.grade == ExecutionRealismGrade.A


def test_real_chain_reconstruction_has_zero_adversarial_violations():
    store = build_store_from_directories(
        quote_dirs=[RAW_EXTRACTED_DIR / "aapl_2014_quote"], trade_dirs=[], oi_dirs=[], equity_files={},
        retrieval_timestamp=datetime.now(timezone.utc), today=date(2026, 9, 3),
    )
    as_of = datetime(2014, 7, 1)
    result = reconstruct_chain_as_of(store, "AAPL", as_of)
    assert len(result.reconstructed_contracts) > 0
    assert len(result.excluded_already_expired) > 0
    violations = contracts_incorrectly_visible_before_first_observation(store, "AAPL", as_of)
    assert violations == ()
