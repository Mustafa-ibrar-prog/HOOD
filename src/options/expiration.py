"""Phase 19, Part 6 — days-to-expiration (DTE) and its bucket taxonomy.

`days_to_expiration` is causal by construction: it only ever subtracts a
contract's fixed `expiration` from the observation date being asked
about -- it never needs (and cannot use) anything about the future.
"""

from __future__ import annotations

import enum
from datetime import date


class DTEBucket(enum.Enum):
    EXPIRED = "expired"  # dte < 0 -- should not occur in a well-formed research panel; kept for defensive completeness
    ZERO_TO_SEVEN = "0-7"
    EIGHT_TO_THIRTY = "8-30"
    THIRTYONE_TO_SIXTY = "31-60"
    SIXTYONE_TO_ONETWENTY = "61-120"
    OVER_ONETWENTY = "120+"


def days_to_expiration(observation_date: date, expiration: date) -> int:
    return (expiration - observation_date).days


def bucket_dte(dte: int) -> DTEBucket:
    if dte < 0:
        return DTEBucket.EXPIRED
    if dte <= 7:
        return DTEBucket.ZERO_TO_SEVEN
    if dte <= 30:
        return DTEBucket.EIGHT_TO_THIRTY
    if dte <= 60:
        return DTEBucket.THIRTYONE_TO_SIXTY
    if dte <= 120:
        return DTEBucket.SIXTYONE_TO_ONETWENTY
    return DTEBucket.OVER_ONETWENTY
