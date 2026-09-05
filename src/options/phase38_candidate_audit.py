"""Phase 38, Part 4 — which research candidates are evaluated this
phase, and why every other one is excluded.

Part 4's explicit instruction: do not resurrect a candidate previously
rejected as inherited-from-underlying/outlier-dependent/cost-fragile/
statistically-unsupported/unaffordable/data-artifact-driven UNLESS
there is genuinely new evidence addressing the EXACT rejection reason.
Phase 37 has recorded zero real live observations as of this phase
(`src.options.phase38_causal_validation_dataset`'s own module docstring
documents this finding) -- there is no new evidence of any kind yet, for
any candidate. Every record below is a factual transcription of each
candidate's most recent, already-documented classification; this module
does not re-derive or re-litigate any of them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateAuditRecord:
    candidate_id: str
    origin_phase: str
    prior_classification: str
    prior_rejection_reason: str
    included_this_phase: bool
    inclusion_or_exclusion_reason: str


CANDIDATE_AUDIT: tuple[CandidateAuditRecord, ...] = (
    CandidateAuditRecord(
        candidate_id="MOMENTUM_BREAKOUT_EXISTING_V1", origin_phase="Phase 28 (live-wired), Phase 35 (frozen+validated)",
        prior_classification="NOT_READY",
        prior_rejection_reason="Phase 35: 2,071 causal entry signals, 2 matched to a real historical option contract, 0 completed round-trip backtest trades -- underpowered (below the 20-trade floor), not a pass or fail.",
        included_this_phase=True,
        inclusion_or_exclusion_reason="The one strategy with a live production adapter (Phase 36) and a real, frozen spec. Included as the primary candidate for live-observation replication (Part 12) -- its rejection reason was DATA VOLUME, exactly what Phase 37's recorder exists to eventually fix. No new evidence exists yet (zero real observations recorded), so it cannot be promoted this phase either, but it is the correct candidate to re-evaluate once real data accumulates.",
    ),
    CandidateAuditRecord(
        candidate_id="options_alpha_round2 family (16 hypotheses)", origin_phase="Phase 31",
        prior_classification="NULL (0 DISCOVERY_SUPPORTED / PROMISING out of 16)",
        prior_rejection_reason="No hypothesis survived cross-sectional + time-series + underlying-control + multiple-testing correction.",
        included_this_phase=False,
        inclusion_or_exclusion_reason="Statistically unsupported after correction, on the free historical dataset. No new live evidence exists this phase to address that finding.",
    ),
    CandidateAuditRecord(
        candidate_id="bucketed options alpha family", origin_phase="Phase 32",
        prior_classification="NULL", prior_rejection_reason="Same as Phase 31, at coarser (bucket) granularity -- still statistically unsupported.",
        included_this_phase=False,
        inclusion_or_exclusion_reason="Same reasoning as Phase 31's family; no new evidence.",
    ),
    CandidateAuditRecord(
        candidate_id="P22-OPT-013 (range-expansion) + its Phase 33 coarse-grain replication (P33-REPL-*)",
        origin_phase="Phase 22 (discovery), Phase 33 (replication attempt)",
        prior_classification="INCONCLUSIVE (all 5 replication hypotheses)",
        prior_rejection_reason="Phase 33: 0/8 testable primary tests significant after correction; no cross-sectional IC could even be computed on the replication dataset (density too sparse); fails 6 of 12 Promising-Finding-Gate criteria simultaneously.",
        included_this_phase=False,
        inclusion_or_exclusion_reason="INCONCLUSIVE, not REJECTED -- technically eligible for re-evaluation with new evidence per Part 4's instruction. But the rejection reason was DATASET DENSITY (the free historical archive's own sparsity), and Phase 37's live recorder has not yet recorded a single real observation -- there is no new evidence addressing that exact reason yet. Excluded this phase; a real candidate for re-evaluation once live data accumulates.",
    ),
)


def candidates_included_this_phase() -> tuple[CandidateAuditRecord, ...]:
    return tuple(c for c in CANDIDATE_AUDIT if c.included_this_phase)


def candidates_excluded_this_phase() -> tuple[CandidateAuditRecord, ...]:
    return tuple(c for c in CANDIDATE_AUDIT if not c.included_this_phase)
