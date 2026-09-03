"""Phase 19, Part 19 — DTE/expiration bucket tests."""

from __future__ import annotations

from datetime import date

from src.options.expiration import DTEBucket, bucket_dte, days_to_expiration


def test_days_to_expiration_basic():
    assert days_to_expiration(date(2022, 1, 1), date(2022, 1, 8)) == 7


def test_days_to_expiration_on_expiration_day_is_zero():
    assert days_to_expiration(date(2022, 1, 8), date(2022, 1, 8)) == 0


def test_days_to_expiration_negative_after_expiration():
    assert days_to_expiration(date(2022, 1, 10), date(2022, 1, 8)) == -2


def test_bucket_boundaries():
    assert bucket_dte(-1) == DTEBucket.EXPIRED
    assert bucket_dte(0) == DTEBucket.ZERO_TO_SEVEN
    assert bucket_dte(7) == DTEBucket.ZERO_TO_SEVEN
    assert bucket_dte(8) == DTEBucket.EIGHT_TO_THIRTY
    assert bucket_dte(30) == DTEBucket.EIGHT_TO_THIRTY
    assert bucket_dte(31) == DTEBucket.THIRTYONE_TO_SIXTY
    assert bucket_dte(60) == DTEBucket.THIRTYONE_TO_SIXTY
    assert bucket_dte(61) == DTEBucket.SIXTYONE_TO_ONETWENTY
    assert bucket_dte(120) == DTEBucket.SIXTYONE_TO_ONETWENTY
    assert bucket_dte(121) == DTEBucket.OVER_ONETWENTY
