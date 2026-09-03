"""Phase 28, Part 4 — the evidence-classification vocabulary for this
phase's provider decision. A distinct, explicitly-specified 5-value
vocabulary (per Part 4's own text), not a re-use of Phase 25's 4-value
Part-4 vocabulary (VERIFIED_AVAILABLE/VERIFIED_UNAVAILABLE/CLAIMED_
AVAILABLE_UNVERIFIED/UNKNOWN) or Phase 26/27's 4-value Part-2/5
vocabularies -- every phase's provider-evidence prompt has specified its
own exact wording, and this module follows Phase 28's literal text
rather than silently substituting an earlier phase's near-synonym.

`VERIFIED_BY_OFFICIAL_DOCUMENTATION` is new this phase: no prior phase's
vocabulary had a tier between "an actual sample was obtained" and "found
via a third party" -- Phase 28 explicitly asks for one. Nothing in this
codebase has ever reached a provider's OWN official docs directly (every
official-docs domain has been EGRESS_BLOCKED every phase this project
has tried), so this tier is defined but, honestly, unused by any real
record built this phase -- see phase28_provider_scorecard.py.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class EvidenceClassification(enum.Enum):
    """Part 4's exact 5-value vocabulary."""

    VERIFIED_BY_ACTUAL_DATA = "verified_by_actual_data"
    VERIFIED_BY_OFFICIAL_DOCUMENTATION = "verified_by_official_documentation"
    CLAIMED_UNVERIFIED = "claimed_unverified"
    EGRESS_BLOCKED = "egress_blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CapabilityEvidence:
    provider: str
    capability: str
    classification: EvidenceClassification
    evidence: str


# ORATS remains ORATS_PROMISING_BUT_UNVERIFIED (Phase 25's exact final
# decision value, src.options.provider_validation_decision.FinalDecision)
# -- no new actual ORATS API call, sample, or official-documentation read
# was made this phase (docs.orats.com remains EGRESS_BLOCKED, re-confirmed
# this phase). Nothing below changes that classification; this constant
# exists so a test can assert the prior phase's finding was not silently
# overwritten.
ORATS_STATUS_UNCHANGED_THIS_PHASE = True
