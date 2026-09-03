"""Phase 19, Part 16 — a richer, 4-state contract-existence classification.

Phase 18's `point_in_time.contract_existed_at()` (untouched by this
phase) returns `bool | None`, which collapses two importantly different
"unknown" situations into a single `None`: "we have never looked" and "we
looked and the evidence is genuinely insufficient to say." This module
adds an explicit 4-state enum on top of the SAME evidence dataclass
(`ContractExistenceEvidence`, reused, not duplicated) for callers -- like
a research panel that wants to report ITS confidence about every
contract-day, not just a single boolean -- that need that distinction.

`point_in_time.py` is not modified: Phase 18 is complete, and Part 16
asks for an ADDITIONAL classification, not a replacement of the existing
one.
"""

from __future__ import annotations

import enum
from datetime import datetime

from src.options.point_in_time import ContractExistenceEvidence


class ExistenceState(enum.Enum):
    KNOWN_EXISTENCE = "known_existence"  # first_listed_date is known AND as_of falls within [first_listed_date, expiration]
    UNKNOWN_EXISTENCE = "unknown_existence"  # as_of is before expiration but first_listed_date is not known -- cannot rule existence in or out
    KNOWN_EXPIRED = "known_expired"  # as_of is strictly after expiration -- definitely does not exist as a live contract
    INSUFFICIENT_PIT_EVIDENCE = "insufficient_pit_evidence"  # the evidence record itself is incomplete/malformed for this query (e.g. no source recorded)


def classify_existence(evidence: ContractExistenceEvidence, *, as_of: datetime) -> ExistenceState:
    if not evidence.source:
        return ExistenceState.INSUFFICIENT_PIT_EVIDENCE
    if as_of.date() > evidence.expiration:
        return ExistenceState.KNOWN_EXPIRED
    if evidence.first_listed_date is None:
        return ExistenceState.UNKNOWN_EXISTENCE
    if as_of.date() < evidence.first_listed_date:
        return ExistenceState.UNKNOWN_EXISTENCE  # a real first-listed date only rules OUT existence before it in the "expired" direction; before-listing is a distinct "not yet" case, still not treated as KNOWN here without a second, independent confirmation
    return ExistenceState.KNOWN_EXISTENCE
