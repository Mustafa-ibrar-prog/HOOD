"""Multiple-hypothesis accounting (Phase 5, section 16).

The more hypotheses/parameter combinations/universes/horizons tested, the
higher the chance ANY given "promising" result is a false positive. This
module doesn't stop anyone from running more experiments — it makes the
total search space visible, computed directly from what ExperimentStore
actually recorded (never a number typed in by hand), so a research report
can show the search history behind any one candidate rather than
presenting it in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.research.experiment import ExperimentRecord


@dataclass(frozen=True)
class SearchSpaceSummary:
    total_experiments: int
    total_hypotheses: int
    total_strategy_families: int
    total_parameter_combinations: int  # distinct (hypothesis_id, sorted-parameters) pairs across all records
    total_universes: int
    total_prediction_horizons: int
    bonferroni_alpha_per_test: float | None  # a naive 0.05-family-wise-error correction, for CONTEXT only

    def render(self) -> str:
        lines = [
            "SEARCH SPACE SUMMARY",
            f"  Total experiments run: {self.total_experiments}",
            f"  Distinct hypotheses tested: {self.total_hypotheses}",
            f"  Distinct strategy families: {self.total_strategy_families}",
            f"  Distinct parameter combinations tried: {self.total_parameter_combinations}",
            f"  Distinct universes tested: {self.total_universes}",
            f"  Distinct prediction horizons tested: {self.total_prediction_horizons}",
        ]
        if self.bonferroni_alpha_per_test is not None:
            lines.append(f"  Naive Bonferroni-adjusted per-test alpha (family-wise 0.05): {self.bonferroni_alpha_per_test:.5f}")
            lines.append("    (context only — this codebase's correlation/significance figures are already documented as NOT valid i.i.d. tests; this does not fix that, it only shows how much more skeptical a real threshold should be given how many tests were run)")
        return "\n".join(lines)


def compute_search_space_summary(records: list[ExperimentRecord]) -> SearchSpaceSummary:
    hypotheses = {r.hypothesis_id for r in records if r.hypothesis_id is not None}
    families = {r.strategy_family for r in records if r.strategy_family is not None}
    universes = {r.universe_name for r in records if r.universe_name is not None}
    horizons = {r.prediction_horizon for r in records if r.prediction_horizon is not None}
    param_combos = {
        (r.hypothesis_id, tuple(sorted(r.parameters.items())))
        for r in records
        if r.hypothesis_id is not None
    }
    total = len(records)
    bonferroni = (0.05 / total) if total > 0 else None
    return SearchSpaceSummary(
        total_experiments=total,
        total_hypotheses=len(hypotheses),
        total_strategy_families=len(families),
        total_parameter_combinations=len(param_combos),
        total_universes=len(universes),
        total_prediction_horizons=len(horizons),
        bonferroni_alpha_per_test=bonferroni,
    )
