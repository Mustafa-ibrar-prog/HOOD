"""Phase 15, Part 13 — the common timestamp standard future data sources
(fundamentals, earnings, options, macro, and anything else beyond daily
Bar) must use to stay causally safe.

Every prior phase's point-in-time discipline was implicit: a Bar's own
`timestamp` IS its causal timestamp (the bar closed at that instant, so
research code using it at t may use it at any as_of >= t). That single-
timestamp shortcut breaks the moment a data source's OBSERVATION doesn't
coincide with its PUBLIC AVAILABILITY — exactly the failure mode Phase 15
was asked to design against: "A fundamental value must not be used at
time t if it was not publicly available at time t," confirmed as a REAL
risk in this phase's own audit (get_financials returns a fiscal quarter's
`period_end_date`, which is NOT when that quarter's numbers became public
-- Apple's quarter ending 2021-09-25 was not publicly known until its
10-K was filed 2021-10-29, over a month later; see
scripts/phase15_data_architecture_audit.py for the full evidence trail).

`EventTimestamps` names the four timestamps Part 13 requires distinguished:

  - event_time:       when the underlying real-world event occurred
                       (a trade executed, a macro period ended, a
                       fundamental's fiscal period ended).
  - observation_time:  when the data was actually recorded/observed
                       (usually == event_time for market data; may differ
                       for e.g. a delayed feed).
  - publication_time:  when the value became PUBLICLY available (a
                       filing date, an earnings-release date, a macro
                       release date). THIS is the causal gate for
                       fundamentals/earnings/macro (Part 13's explicit
                       instruction) — a strategy may not use the value
                       before this instant, no matter how early
                       event_time was.
  - ingestion_time:    when THIS codebase's pipeline actually fetched and
                       stored the value — never a causal timestamp (it
                       reflects engineering convenience, not market
                       reality), kept only for audit/debugging.

`CausalTimestampPolicy` says, per data category, which of the first three
fields actually gates "was this knowable at time t" (Part 13: market data
uses its own event/observation timestamp; fundamentals/earnings/macro use
publication_time). `assert_no_lookahead`/`is_knowable_at` apply that
policy uniformly, and are what Part 19's "safety against future
publication dates" test exercises.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime


class CausalTimestampPolicy(enum.Enum):
    """Which EventTimestamps field is the causal gate for a data category."""

    EVENT_TIME = "event_time"
    OBSERVATION_TIME = "observation_time"
    PUBLICATION_TIME = "publication_time"


class PointInTimeViolation(RuntimeError):
    """Raised when a value's causal timestamp is unknown or is after the
    `as_of` instant a caller claims to be reasoning at — the equivalent,
    for non-Bar data, of every prior phase's "no lookahead" test."""


@dataclass(frozen=True)
class EventTimestamps:
    """The four causal timestamps for one observation. All optional
    because not every source can supply all four (in particular:
    publication_time is frequently the one a source does NOT supply — see
    get_financials in this phase's audit — and that absence is itself the
    signal that a source is not point-in-time-safe, not something to fill
    in with a guess)."""

    event_time: datetime | None = None
    observation_time: datetime | None = None
    publication_time: datetime | None = None
    ingestion_time: datetime | None = None

    def causal_timestamp(self, policy: CausalTimestampPolicy) -> datetime | None:
        """The single timestamp that answers "was this knowable at time t"
        under `policy`. Returns None (never a fallback guess) when the
        policy's field wasn't supplied — a caller must treat None as
        "cannot prove causality," never as "assume it was always known."""
        return getattr(self, policy.value)


def is_knowable_at(ts: EventTimestamps, *, policy: CausalTimestampPolicy, as_of: datetime) -> bool:
    """True only if `policy`'s field is present AND <= as_of. A missing
    causal timestamp is NOT knowable (fails closed, same convention as
    every other store in this codebase)."""
    causal = ts.causal_timestamp(policy)
    if causal is None:
        return False
    return causal <= as_of


def assert_no_lookahead(ts: EventTimestamps, *, policy: CausalTimestampPolicy, as_of: datetime) -> None:
    """Raises PointInTimeViolation if `ts` is not knowable at `as_of` under
    `policy` — either because the causal field is missing (source is not
    point-in-time-safe for this policy) or because it is strictly after
    as_of (a genuine lookahead)."""
    causal = ts.causal_timestamp(policy)
    if causal is None:
        raise PointInTimeViolation(
            f"cannot verify point-in-time safety under policy={policy.value}: "
            f"the causal timestamp field is not populated on this observation"
        )
    if causal > as_of:
        raise PointInTimeViolation(
            f"lookahead: causal timestamp {causal.isoformat()} (policy={policy.value}) "
            f"is after as_of={as_of.isoformat()}"
        )
