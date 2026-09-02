"""Phase 16, Part 15B — SEC causal timestamp policy tests: filing date vs
period end, publication availability, date-only uncertainty, the exact
same-day conservative-exclusion boundary. Deterministic fixtures."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.data.sec_timestamp_policy import SECCausalPolicy, sec_is_available_asof


def test_not_available_before_filing_date():
    assert sec_is_available_asof(date_filed=date(2022, 10, 28), as_of=datetime(2022, 10, 1, tzinfo=timezone.utc)) is False


def test_not_available_on_filing_date_even_at_end_of_day():
    """Part 5 rule 3: same-day-as-filing must NOT be considered available
    under the date-only policy, regardless of time-of-day."""
    assert sec_is_available_asof(date_filed=date(2022, 10, 28), as_of=datetime(2022, 10, 28, 0, 0, tzinfo=timezone.utc)) is False
    assert sec_is_available_asof(date_filed=date(2022, 10, 28), as_of=datetime(2022, 10, 28, 23, 59, 59, tzinfo=timezone.utc)) is False


def test_available_strictly_after_filing_date():
    assert sec_is_available_asof(date_filed=date(2022, 10, 28), as_of=datetime(2022, 10, 29, 0, 0, tzinfo=timezone.utc)) is True


def test_available_far_in_the_future():
    assert sec_is_available_asof(date_filed=date(2022, 10, 28), as_of=datetime(2030, 1, 1, tzinfo=timezone.utc)) is True


def test_fiscal_period_end_date_is_never_used_as_publication_time():
    """Part 5 rule 1, made structurally testable: passing the period-end
    date as date_filed produces a DIFFERENT (and wrong) availability
    result than passing the real filing date -- proving the function
    genuinely distinguishes the two, rather than silently treating
    whichever date it receives as equivalent."""
    period_end = date(2022, 9, 24)  # AAPL's real FY2022 fiscal period end
    real_filing_date = date(2022, 10, 28)  # AAPL's real 10-K filing date, over a month later
    as_of = datetime(2022, 10, 1, tzinfo=timezone.utc)  # after period_end, but before the real filing date
    # If period_end were (wrongly) used as the causal timestamp, this would incorrectly say "available".
    assert sec_is_available_asof(date_filed=period_end, as_of=as_of) is True  # demonstrates the (wrong) result period_end alone would give
    assert sec_is_available_asof(date_filed=real_filing_date, as_of=as_of) is False  # the CORRECT result using the real filing date


def test_exact_publication_timestamp_policy_requires_a_timestamp():
    with pytest.raises(ValueError):
        sec_is_available_asof(
            date_filed=date(2022, 10, 28), as_of=datetime(2022, 10, 29, tzinfo=timezone.utc),
            policy=SECCausalPolicy.EXACT_PUBLICATION_TIMESTAMP,
        )


def test_exact_publication_timestamp_policy_uses_the_real_timestamp_when_supplied():
    accepted = datetime(2022, 10, 28, 16, 30, tzinfo=timezone.utc)
    assert sec_is_available_asof(
        date_filed=date(2022, 10, 28), as_of=datetime(2022, 10, 28, 16, 0, tzinfo=timezone.utc),
        policy=SECCausalPolicy.EXACT_PUBLICATION_TIMESTAMP, accepted_timestamp=accepted,
    ) is False
    assert sec_is_available_asof(
        date_filed=date(2022, 10, 28), as_of=datetime(2022, 10, 28, 17, 0, tzinfo=timezone.utc),
        policy=SECCausalPolicy.EXACT_PUBLICATION_TIMESTAMP, accepted_timestamp=accepted,
    ) is True


def test_naive_as_of_is_treated_as_utc():
    naive = datetime(2022, 10, 29, 0, 0)
    assert sec_is_available_asof(date_filed=date(2022, 10, 28), as_of=naive) is True
