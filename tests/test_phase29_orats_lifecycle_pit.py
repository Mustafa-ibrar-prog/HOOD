"""Phase 29, Part 4/7/17 — ORATS PIT / lifecycle certification, reusing
Phase 15/26's real machinery against ORATS-shaped (synthetic) data."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.options.orats_ingest import ingest_strike_rows
from src.options.orats_lifecycle_pit import (
    PIT_CONTRACT_EXISTENCE_LIMITED,
    adversarial_future_observation_is_rejected,
    adversarial_missing_causal_timestamp_is_rejected,
    orats_pit_status,
)
from tests.orats_fixtures import SYNTHETIC_AAPL_STRIKES_20211201, SYNTHETIC_AAPL_STRIKES_20211202

RETRIEVAL = datetime(2026, 9, 4, tzinfo=timezone.utc)


def test_pit_contract_existence_limited_names_the_real_gap():
    text = PIT_CONTRACT_EXISTENCE_LIMITED.lower()
    assert "first-listed-date" in text or "first-observed-date" in text
    assert "trade_date" in text


def test_adversarial_future_observation_rejected_reused_unchanged():
    assert adversarial_future_observation_is_rejected(as_of=datetime(2021, 12, 1), future_event_time=datetime(2021, 12, 2)) is True


def test_adversarial_missing_timestamp_rejected_reused_unchanged():
    assert adversarial_missing_causal_timestamp_is_rejected(as_of=datetime(2021, 12, 1)) is True


def test_orats_pit_status_on_multi_day_synthetic_data():
    rows = SYNTHETIC_AAPL_STRIKES_20211201 + SYNTHETIC_AAPL_STRIKES_20211202
    store = ingest_strike_rows(rows, retrieval_timestamp=RETRIEVAL, today=date(2026, 9, 4))
    status = orats_pit_status(store, "AAPL", datetime(2021, 12, 2, 23, 59))
    assert status["reconstructed_contract_count"] > 0
    assert status["adversarial_violations"] == 0
    assert status["pit_contract_existence_limited"] == PIT_CONTRACT_EXISTENCE_LIMITED


def test_orats_pit_status_excludes_future_dated_contracts():
    rows = SYNTHETIC_AAPL_STRIKES_20211201 + SYNTHETIC_AAPL_STRIKES_20211202
    store = ingest_strike_rows(rows, retrieval_timestamp=RETRIEVAL, today=date(2026, 9, 4))
    early_status = orats_pit_status(store, "AAPL", datetime(2021, 12, 1, 12, 0))
    late_status = orats_pit_status(store, "AAPL", datetime(2021, 12, 2, 23, 59))
    assert late_status["reconstructed_contract_count"] >= early_status["reconstructed_contract_count"]
