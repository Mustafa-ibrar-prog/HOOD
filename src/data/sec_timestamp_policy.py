"""Phase 16, Part 5 — the SEC causal timestamp policy.

Confirmed by real probe (see sec_filing_store.py's module docstring):
get_sec_filing_index supplies ONLY a filing DATE (date_filed), never a
time-of-day / accepted-timestamp. Part 5 is explicit that this
uncertainty must be represented, not papered over with an invented
4:00pm-style timestamp. This module is that representation: a small,
separate causal-availability function (not bolted onto
src.data.timestamp_model.EventTimestamps, which stays a general-purpose
four-timestamp model with no opinion about date-only uncertainty) plus
the seven numbered rules from Part 5, each directly testable.

Rule-by-rule mapping (Part 5):
  1. fiscal_period_end_date MUST NEVER be treated as publication time.
     -> enforced structurally: `sec_is_available_asof` never even looks
        at period_end; it takes date_filed as an explicit, separate
        argument. There is no code path that could substitute one for
        the other.
  2. A fact is causally available only at the real SEC filing/accepted
     timestamp.
     -> `sec_is_available_asof`'s entire purpose.
  3. Date-only uncertainty must be handled conservatively: available
     only strictly AFTER the filing date; same-day is NOT available.
     -> `sec_is_available_asof`'s PUBLICATION_DATE_ONLY branch.
  4. Amendments must not overwrite the original filing.
  5. Each filing retains its own identity (filing_id).
  6. Never collapse revised facts into one timeless "truth".
  7. Multiple filings of the same concept must preserve their historical
     sequence.
     -> rules 4-7 are store-level guarantees, not timestamp-policy
        guarantees: SECFilingStore never deletes or merges records by
        concept (see its save_facts dedupe key, which includes
        filing_id), and get_available_facts (sec_snapshot.py) returns
        every filing's version of a fact rather than one collapsed
        value — see tests/test_sec_filing_store.py and
        tests/test_sec_snapshot_and_dataset.py for the regression tests.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone


class SECCausalPolicy(enum.Enum):
    PUBLICATION_DATE_ONLY = "publication_date_only"  # conservative: strictly-after-filing-date only (the ONLY policy this phase's real data supports, since no time-of-day is ever available)
    EXACT_PUBLICATION_TIMESTAMP = "exact_publication_timestamp"  # for a FUTURE source that does supply a real accepted timestamp; not exercised by real data this phase


def sec_is_available_asof(
    *,
    date_filed: date,
    as_of: datetime,
    policy: SECCausalPolicy = SECCausalPolicy.PUBLICATION_DATE_ONLY,
    accepted_timestamp: datetime | None = None,
) -> bool:
    """Part 5's three numbered availability rules, applied directly:

    - PUBLICATION_DATE_ONLY (the only policy real SEC data from this
      connector supports): available iff as_of's calendar date is
      STRICTLY AFTER date_filed. On the filing date itself, conservative
      exclusion applies (rule 3's "before a known accepted timestamp, it
      must not be considered available" — with no accepted timestamp at
      all, the whole filing date is treated as "before").
    - EXACT_PUBLICATION_TIMESTAMP: available iff accepted_timestamp is
      supplied and accepted_timestamp <= as_of. Raises if the policy is
      requested but no accepted_timestamp was supplied — this phase's
      real data never supplies one, so silently falling back to the
      date-only rule here would hide that gap rather than surface it.
    """
    if policy == SECCausalPolicy.EXACT_PUBLICATION_TIMESTAMP:
        if accepted_timestamp is None:
            raise ValueError(
                "SECCausalPolicy.EXACT_PUBLICATION_TIMESTAMP requires accepted_timestamp; "
                "no real SEC filing probed this phase supplies one -- use PUBLICATION_DATE_ONLY instead"
            )
        return accepted_timestamp <= as_of

    as_of_utc = as_of.astimezone(timezone.utc) if as_of.tzinfo else as_of
    return as_of_utc.date() > date_filed
