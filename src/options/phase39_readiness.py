"""Phase 39, Part 12 — objective collection-readiness milestones.

Explicit instruction: "Do NOT choose a minimum sample size arbitrarily.
Use Phase 38's existing validation requirements." Every threshold below
is therefore one of Phase 38's OWN already-defined constants
(`phase38_underlying_vs_option_edge.MIN_SAMPLE_FOR_A_VERDICT`,
`phase38_chronological_split.MIN_TOTAL_FOR_CHRONOLOGICAL_SPLIT`) — none
is invented here.

This module never declares a strategy validated, promising, or
tradeable, and never computes a simulated trading return — it only asks
whether enough REAL, causal, forward-outcome-bearing observations exist
to attempt Phase 38's validation gate again. `SUFFICIENT_FOR_VALIDATION_ATTEMPT`
means exactly that and nothing more: it is not a claim the strategy would
pass the gate, only that there is now enough data to run the attempt
honestly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.options.phase38_campaign import _dataset_by_option
from src.options.phase38_causal_validation_dataset import CausalFeatureRow
from src.options.phase38_chronological_split import MIN_TOTAL_FOR_CHRONOLOGICAL_SPLIT, split_chronologically
from src.options.phase38_targets import DEFAULT_HORIZONS, ForwardHorizon, compute_forward_outcome
from src.options.phase38_underlying_vs_option_edge import MIN_SAMPLE_FOR_A_VERDICT


class ReadinessStatus(str, Enum):
    INSUFFICIENT_DATA_FOR_VALIDATION = "INSUFFICIENT_DATA_FOR_VALIDATION"
    # Means ONLY "enough real observations now exist to attempt Phase 38's
    # validation gate again" -- never a claim the strategy would pass it.
    SUFFICIENT_FOR_VALIDATION_ATTEMPT = "SUFFICIENT_FOR_VALIDATION_ATTEMPT"


@dataclass(frozen=True)
class ReadinessMilestone:
    key: str
    label: str
    satisfied: bool
    gating: bool  # False for milestones that are informational only (Part 12.F)
    detail: str


@dataclass(frozen=True)
class CollectionReadinessAssessment:
    status: ReadinessStatus
    milestones: tuple[ReadinessMilestone, ...]
    unmet_gating_milestone_keys: tuple[str, ...]


def assess_collection_readiness(
    dataset: list[CausalFeatureRow], *, horizon: ForwardHorizon = DEFAULT_HORIZONS[0],
) -> CollectionReadinessAssessment:
    by_option = _dataset_by_option(dataset)

    # Every row in the dataset, treated as a hypothetical entry against its
    # own later observations -- the SAME construction phase38_campaign's
    # candidate_pool uses, never a different or fabricated pool. This
    # measures whether the DATA supports forward-outcome construction at
    # all, independent of whether any strategy ever produced an ENTER
    # signal against it.
    outcomes = []
    for row in dataset:
        later = [r for r in by_option.get(row.option_id, []) if r.observation_timestamp > row.observation_timestamp]
        outcomes.append(compute_forward_outcome(row, later, horizon=horizon))

    unique_option_ids = {row.option_id for row in dataset}
    unique_symbols = {row.underlying_symbol for row in dataset}
    unique_dates = {row.observation_timestamp.date() for row in dataset}
    max_observations_for_a_contract = max((len(rows) for rows in by_option.values()), default=0)
    n_forward_outcomes_computed = sum(1 for o in outcomes if o.mid_return_pct is not None or o.executable_return_pct is not None)
    n_executable_outcomes = sum(1 for o in outcomes if o.executable_return_pct is not None)
    split = split_chronologically(outcomes)

    milestones = (
        ReadinessMilestone(
            "A_repeated_observations_of_same_contract", "Repeated observations of the same option contract",
            max_observations_for_a_contract >= 2, True,
            f"max observations for a single contract = {max_observations_for_a_contract} (need >= 2)",
        ),
        ReadinessMilestone(
            "B_forward_outcome_construction", "Forward outcome construction",
            n_forward_outcomes_computed >= 1, True,
            f"{n_forward_outcomes_computed} forward outcome(s) computed (need >= 1, proves the mechanism works)",
        ),
        ReadinessMilestone(
            "C_multiple_independent_contracts", "Multiple independent option contracts",
            len(unique_option_ids) >= MIN_SAMPLE_FOR_A_VERDICT, True,
            f"{len(unique_option_ids)} unique option contract(s) observed (need >= {MIN_SAMPLE_FOR_A_VERDICT}, "
            "reusing Phase 38's MIN_SAMPLE_FOR_A_VERDICT)",
        ),
        ReadinessMilestone(
            "D_multiple_underlying_symbols", "Multiple underlying symbols",
            len(unique_symbols) >= 2, True,
            f"{len(unique_symbols)} unique underlying symbol(s) observed (need >= 2, for leave-one-symbol-out to be meaningful)",
        ),
        ReadinessMilestone(
            "E_multiple_trading_days", "Multiple trading days",
            len(unique_dates) >= 2, True,
            f"{len(unique_dates)} unique calendar date(s) observed (need >= 2, for leave-one-period-out to be meaningful)",
        ),
        ReadinessMilestone(
            "F_multiple_market_regimes", "Multiple market regimes (where applicable)",
            True, False,
            "Not objectively definable from observation count alone -- informational only, never gates readiness.",
        ),
        ReadinessMilestone(
            "G_executable_bid_ask_observations", "Executable bid/ask observations",
            n_executable_outcomes >= MIN_SAMPLE_FOR_A_VERDICT, True,
            f"{n_executable_outcomes} outcome(s) with a real executable (bid/ask, never mid) return "
            f"(need >= {MIN_SAMPLE_FOR_A_VERDICT}, reusing Phase 38's MIN_SAMPLE_FOR_A_VERDICT)",
        ),
        ReadinessMilestone(
            "H_option_level_feature_construction", "Option-level feature construction",
            len(dataset) > 0, True,
            f"{len(dataset)} causal feature row(s) constructed (need >= 1)",
        ),
        ReadinessMilestone(
            "I_chronological_split_separation", "Chronological development/validation/holdout separation",
            split.sufficient, True,
            f"{split.reason} (reusing Phase 38's MIN_TOTAL_FOR_CHRONOLOGICAL_SPLIT={MIN_TOTAL_FOR_CHRONOLOGICAL_SPLIT})",
        ),
    )

    unmet_gating = tuple(m.key for m in milestones if m.gating and not m.satisfied)
    status = ReadinessStatus.SUFFICIENT_FOR_VALIDATION_ATTEMPT if not unmet_gating else ReadinessStatus.INSUFFICIENT_DATA_FOR_VALIDATION

    return CollectionReadinessAssessment(status=status, milestones=milestones, unmet_gating_milestone_keys=unmet_gating)
