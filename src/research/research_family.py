"""Phase 7, Part 2: formal research-family accounting.

Builds directly on ExperimentStore (never a parallel store) — a "family"
here is simply the set of ExperimentRecords sharing a `research_family_id`
(a Phase 7 addition to ExperimentRecord). This module answers exactly the
questions Part 2 asks for, computed FROM the stored records, never
hand-typed:
  - parameter_grid_size / number_of_variants_tested per family
  - datasets/universe/feature_set used
  - prior experiments in the same family
  - whether a result influenced future hypothesis generation (an
    explicit, honest boolean the CALLER must set — this module cannot
    infer intent, only record what it's told)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.research.experiment import ExperimentRecord, ExperimentStore


@dataclass(frozen=True)
class ResearchFamilySummary:
    research_family_id: str
    experiment_count: int
    hypothesis_ids: tuple[str, ...]
    strategy_families: tuple[str, ...]
    distinct_parameter_combinations: int
    universes_used: tuple[str, ...]
    feature_sets_used: tuple[str, ...]
    datasets_used: tuple[str, ...]  # data_version values
    earliest_experiment_at: str | None
    latest_experiment_at: str | None

    def render(self) -> str:
        return (
            f"RESEARCH FAMILY {self.research_family_id}\n"
            f"  experiments={self.experiment_count}  hypotheses={list(self.hypothesis_ids)}  strategy_families={list(self.strategy_families)}\n"
            f"  distinct_parameter_combinations={self.distinct_parameter_combinations}\n"
            f"  universes={list(self.universes_used)}  datasets={list(self.datasets_used)}\n"
            f"  span: {self.earliest_experiment_at} .. {self.latest_experiment_at}"
        )


def summarize_research_family(store: ExperimentStore, research_family_id: str) -> ResearchFamilySummary:
    records = store.query(research_family_id=research_family_id)
    return _summarize(research_family_id, records)


def _summarize(research_family_id: str, records: Sequence[ExperimentRecord]) -> ResearchFamilySummary:
    if not records:
        return ResearchFamilySummary(research_family_id, 0, (), (), 0, (), (), (), None, None)
    hyp_ids = tuple(sorted({r.hypothesis_id for r in records if r.hypothesis_id}))
    families = tuple(sorted({r.strategy_family for r in records if r.strategy_family}))
    param_combos = {tuple(sorted(r.parameters.items())) for r in records}
    universes = tuple(sorted({r.universe_name for r in records if r.universe_name}))
    feature_sets = tuple(sorted({r.feature_version for r in records if r.feature_version}))
    datasets = tuple(sorted({r.data_version for r in records if r.data_version}))
    timestamps = sorted(r.created_at for r in records)
    return ResearchFamilySummary(
        research_family_id=research_family_id, experiment_count=len(records), hypothesis_ids=hyp_ids, strategy_families=families,
        distinct_parameter_combinations=len(param_combos), universes_used=universes, feature_sets_used=feature_sets, datasets_used=datasets,
        earliest_experiment_at=timestamps[0].isoformat() if timestamps else None, latest_experiment_at=timestamps[-1].isoformat() if timestamps else None,
    )


def prior_experiments_in_family(store: ExperimentStore, research_family_id: str, *, before_experiment_id: str | None = None) -> tuple[ExperimentRecord, ...]:
    """Every experiment already recorded in this family — the direct
    answer to "how many materially similar hypotheses have we already
    tried?" for anything sharing a research_family_id. If
    `before_experiment_id` is given, only returns experiments recorded
    strictly before it (chronologically), useful for reconstructing what
    was actually known at the time a given experiment ran."""
    records = store.query(research_family_id=research_family_id)
    if before_experiment_id is None:
        return tuple(sorted(records, key=lambda r: r.created_at))
    target = next((r for r in records if r.experiment_id == before_experiment_id), None)
    if target is None:
        return tuple(sorted(records, key=lambda r: r.created_at))
    return tuple(sorted((r for r in records if r.created_at < target.created_at), key=lambda r: r.created_at))
