"""Phase 19, Part 15/19 — additive quality-check extensions: missing
bars, corporate-action inconsistencies, suspicious/incomplete contract
histories."""

from __future__ import annotations

from datetime import date, timedelta

from src.options.instrument import OptionContract
from src.options.quality import (
    find_corporate_action_inconsistency,
    find_missing_business_days,
    find_suspicious_flat_price_run,
)


def test_find_missing_business_days_detects_a_gap():
    d0 = date(2022, 1, 3)  # Monday
    dates = [d0, d0 + timedelta(days=1), d0 + timedelta(days=3)]  # Tue present, Wed missing, Thu present
    missing = find_missing_business_days(dates)
    assert d0 + timedelta(days=2) in missing


def test_find_missing_business_days_ignores_weekends():
    d0 = date(2022, 1, 3)  # Monday
    d1 = date(2022, 1, 10)  # next Monday, contiguous business days present
    dates = [d0 + timedelta(days=i) for i in range(5)] + [d1]
    missing = find_missing_business_days(dates)
    assert missing == []


def test_find_missing_business_days_needs_at_least_two_dates():
    assert find_missing_business_days([date(2022, 1, 3)]) == []


def test_find_suspicious_flat_price_run_flags_long_run():
    closes = [0.01] * 12 + [0.05, 0.10]
    issues = find_suspicious_flat_price_run(closes, min_run_length=10)
    assert len(issues) == 1
    assert issues[0].code == "SUSPICIOUS_FLAT_PRICE_RUN"
    assert issues[0].severity == "WARNING"


def test_find_suspicious_flat_price_run_ignores_short_run():
    closes = [0.01] * 3 + [0.10, 0.20]
    assert find_suspicious_flat_price_run(closes, min_run_length=10) == []


def test_find_suspicious_flat_price_run_flags_trailing_run():
    closes = [1.0, 0.5] + [0.01] * 15
    issues = find_suspicious_flat_price_run(closes, min_run_length=10)
    assert len(issues) == 1


def test_find_corporate_action_inconsistency_flags_nonstandard_multiplier_claimed_standard():
    c = OptionContract(underlying_symbol="AAPL", option_id="c1", call_put="call", strike=100.0, expiration=date(2022, 1, 21), contract_multiplier=200)
    issues = find_corporate_action_inconsistency(c)
    assert any(i.code == "INCONSISTENT_MULTIPLIER" for i in issues)


def test_find_corporate_action_inconsistency_clean_for_standard_contract():
    c = OptionContract(underlying_symbol="AAPL", option_id="c1", call_put="call", strike=100.0, expiration=date(2022, 1, 21))
    assert find_corporate_action_inconsistency(c) == []


def test_find_corporate_action_inconsistency_clean_for_documented_adjustment():
    c = OptionContract(
        underlying_symbol="AAPL", option_id="c1", call_put="call", strike=100.0, expiration=date(2022, 1, 21),
        contract_multiplier=300, is_standard_deliverable=False, deliverable_note="adjusted for 3:1 split",
    )
    assert find_corporate_action_inconsistency(c) == []
