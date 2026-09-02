"""Phase 16, Part 8 — the point-in-time snapshot engine.

`get_available_facts` answers "what was known at timestamp T" for one
symbol's SEC facts: it filters to exactly the facts whose filing date
satisfies `sec_timestamp_policy.sec_is_available_asof` at the given
`as_of` — nothing else. `latest_known_value` builds on that to answer
Part 11's neutral "latest_known_X" question: among the facts knowable at
`as_of`, which is the most recently reported (by fiscal period, tie-
broken by filing date so a later amendment wins) consolidated value for
one normalized concept.

Deliberately NOT here: any return, alpha, or trading computation. This
module answers "what information existed," never "was it predictive."
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from src.data.sec_concepts import CONCEPT_MAP
from src.data.sec_filing_store import SECFactRecord, SECFilingStore
from src.data.sec_timestamp_policy import SECCausalPolicy, sec_is_available_asof


def get_available_facts(
    facts: Sequence[SECFactRecord], *, as_of: datetime, policy: SECCausalPolicy = SECCausalPolicy.PUBLICATION_DATE_ONLY
) -> list[SECFactRecord]:
    """Every fact whose filing is causally available at `as_of` under
    `policy` — no quality filtering, no concept filtering. This is the
    literal "get_available_facts(security, as_of_timestamp)" primitive
    Part 8 asks for."""
    return [f for f in facts if sec_is_available_asof(date_filed=f.date_filed, as_of=as_of, policy=policy)]


def get_available_facts_for_symbol(
    store: SECFilingStore, symbol: str, *, as_of: datetime, policy: SECCausalPolicy = SECCausalPolicy.PUBLICATION_DATE_ONLY
) -> list[SECFactRecord]:
    return get_available_facts(store.load_facts(symbol), as_of=as_of, policy=policy)


def latest_known_value(available_facts: Sequence[SECFactRecord], *, normalized_concept: str) -> SECFactRecord | None:
    """Among already-filtered `available_facts` (i.e. the output of
    get_available_facts — this function does NOT itself apply the
    causal-availability filter, so callers must pass already-available
    facts), the most recent consolidated (axises == ()) value for
    `normalized_concept`. Ties (the same fiscal period reported by more
    than one filing — an amendment) are broken by the LATER date_filed,
    per Part 5 rule 4: a later amendment is a later information event,
    so it is what "latest known" should reflect — without deleting or
    overwriting the earlier version anywhere in the store itself."""
    source_concepts = {m.source_concept for m in CONCEPT_MAP if m.normalized_concept == normalized_concept}
    candidates = [f for f in available_facts if f.concept in source_concepts and f.is_consolidated_total]
    if not candidates:
        return None
    return max(candidates, key=lambda f: (f.period_end, f.date_filed))
