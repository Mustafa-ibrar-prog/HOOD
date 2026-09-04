"""Phase 31, Part 18/18 — the campaign orchestrator.

Ties every other `phase31_*` module together into one real, end-to-end
run: preregister (Part 1) -> build the real panel (foundational adapter)
-> residualize against the underlying (Part 7) -> for each hypothesis,
compute cross-sectional + time-series evidence (Parts 5-6), underlying
control (Part 2), robustness (Part 11), temporal alignment (Part 13),
symbol-cluster bootstrap, a 6-method placebo battery (Part 12),
affordability/liquidity/cost reporting (Parts 8-9), and an outlier-
trimmed IC -> correct for multiple testing ACROSS the full family (Part
10) -> classify (Part 14) -> evaluate the Promising Finding Gate (Part
15). No hypothesis is ever turned into a strategy here (Part 16) — this
module's only output is a `Phase31Report`, a research record.

COMPUTATIONAL-BUDGET DISCLOSURE (not hidden): `n_placebo_trials` and
`n_bootstrap_resamples` default lower than the reused modules' own
defaults (200/1000) specifically for this campaign's actual run, given
the real free dataset's scale even after `phase31_panel_builder`'s
contract subsample — see `docs/phase31_options_alpha_round2.md` for the
exact values used and why.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from src.options.dependence_bootstrap import SymbolClusterBootstrapReport, symbol_cluster_bootstrap_ic
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.phase31_affordability_liquidity import (
    AffordabilityFilterReport,
    CostSensitivityResult,
    LiquidityReport,
    affordability_filter_report,
    cost_sensitivity_report,
    liquidity_report,
)
from src.options.phase31_classification import DiscoveryClassification, HypothesisEvidence, classify_hypothesis
from src.options.phase31_evidence import (
    CrossSectionalEvidence,
    TimeSeriesEvidence,
    evaluate_cross_sectional_evidence,
    evaluate_time_series_evidence,
)
from src.options.phase31_gate import GateResult, evaluate_gate
from src.options.phase31_hypotheses import build_hypotheses, register_all
from src.options.phase31_panel_builder import DEFAULT_MAX_CONTRACTS_PER_UNDERLYING, build_panel_rows
from src.options.phase31_robustness import (
    RobustnessReport,
    TemporalAlignmentResult,
    evaluate_robustness,
    evaluate_temporal_alignment,
    multiple_testing_across_family,
)
from src.options.phase31_underlying_control import economically_scoped_rows, residualize_against_underlying, underlying_control_comparison
from src.options.placebo_extensions import (
    block_preserving_shuffle_placebo,
    sign_flipped_target_diagnostic,
    symbol_identity_shuffle_placebo,
    within_symbol_time_shuffle_placebo,
)
from src.research.cross_sectional_placebo import CrossSectionalPlaceboResult, random_feature_control, shuffled_signal_placebo, time_shuffled_target_placebo
from src.research.hypothesis import Hypothesis, HypothesisRegistry
from src.research.preregistration import PreregistrationStore, require_preregistered

RESIDUALIZATION_HORIZON = 5
DEFAULT_N_PLACEBO_TRIALS = 30
DEFAULT_N_BOOTSTRAP_RESAMPLES = 150


def _trim_outliers(panel_rows: Sequence[dict], target_col: str, *, frac: float = 0.01) -> list[dict]:
    values = sorted(r[target_col] for r in panel_rows if r.get(target_col) is not None)
    if len(values) < 20:
        return list(panel_rows)
    n = len(values)
    lo_cut, hi_cut = values[int(n * frac)], values[int(n * (1 - frac)) - 1]
    return [r for r in panel_rows if r.get(target_col) is None or lo_cut <= r[target_col] <= hi_cut]


def _outlier_trimmed_ic(panel_rows: Sequence[dict], *, feature_col: str, target_col: str) -> float | None:
    trimmed = _trim_outliers(panel_rows, target_col)
    evidence = evaluate_cross_sectional_evidence(trimmed, feature_col=feature_col, target_col=target_col)
    return evidence.report.ic_summary.average_ic if (evidence.applicable and evidence.report is not None) else None


def evaluate_one_hypothesis(
    hypothesis: Hypothesis, panel_rows: Sequence[dict], *,
    n_placebo_trials: int = DEFAULT_N_PLACEBO_TRIALS, n_bootstrap_resamples: int = DEFAULT_N_BOOTSTRAP_RESAMPLES,
    min_universe_size: int = 3,
) -> HypothesisEvidence:
    feature_col = hypothesis.required_features[0]
    target_col = hypothesis.target_definition
    horizon = hypothesis.prediction_horizon_bars
    underlying_return_col = f"forward_underlying_return_{horizon}"

    cs_evidence = evaluate_cross_sectional_evidence(panel_rows, feature_col=feature_col, target_col=target_col, min_universe_size=min_universe_size)
    ts_evidence = evaluate_time_series_evidence(panel_rows, feature_col=feature_col, target_col=target_col, horizon_bars=horizon)

    underlying_control = None
    if any(r.get(underlying_return_col) is not None for r in panel_rows):
        underlying_control = underlying_control_comparison(
            panel_rows, option_feature_col=feature_col, target_col=target_col,
            underlying_return_col=underlying_return_col, underlying_target_col=underlying_return_col,
            min_universe_size=min_universe_size,
        )

    robustness = evaluate_robustness(panel_rows, feature_col=feature_col, target_col=target_col, min_universe_size=min_universe_size)
    temporal = evaluate_temporal_alignment(panel_rows, feature_col=feature_col, target_col=target_col, min_universe_size=min_universe_size)

    scoped = economically_scoped_rows(panel_rows)
    bootstrap = symbol_cluster_bootstrap_ic(
        scoped, feature_col=feature_col, target_col=target_col, n_resamples=n_bootstrap_resamples, min_universe_size=min_universe_size,
    )

    placebo_results: dict[str, CrossSectionalPlaceboResult] = {
        "shuffled_signal_placebo": shuffled_signal_placebo(scoped, feature_col=feature_col, target_col=target_col, n_trials=n_placebo_trials, min_universe_size=min_universe_size),
        "random_feature_control": random_feature_control(scoped, target_col=target_col, n_trials=n_placebo_trials, min_universe_size=min_universe_size),
        "time_shuffled_target_placebo": time_shuffled_target_placebo(scoped, feature_col=feature_col, target_col=target_col, n_trials=n_placebo_trials, min_universe_size=min_universe_size),
        "within_symbol_time_shuffle_placebo": within_symbol_time_shuffle_placebo(panel_rows, feature_col=feature_col, target_col=target_col, n_trials=n_placebo_trials, min_universe_size=min_universe_size),
        "symbol_identity_shuffle_placebo": symbol_identity_shuffle_placebo(panel_rows, feature_col=feature_col, target_col=target_col, n_trials=n_placebo_trials, min_universe_size=min_universe_size),
        "block_preserving_shuffle_placebo": block_preserving_shuffle_placebo(panel_rows, feature_col=feature_col, target_col=target_col, n_trials=n_placebo_trials, min_universe_size=min_universe_size),
        "sign_flipped_target_diagnostic": sign_flipped_target_diagnostic(panel_rows, feature_col=feature_col, target_col=target_col, min_universe_size=min_universe_size),
    }

    affordability = affordability_filter_report(panel_rows)
    liquidity = liquidity_report(panel_rows)
    gross_effect = cs_evidence.report.quantile_report.spread_q5_minus_q1 if (cs_evidence.applicable and cs_evidence.report) else None
    cost_sensitivity = cost_sensitivity_report(gross_effect, liquidity)

    outlier_trimmed_ic = _outlier_trimmed_ic(panel_rows, feature_col=feature_col, target_col=target_col)

    return HypothesisEvidence(
        hypothesis_id=hypothesis.hypothesis_id, feature_col=feature_col, target_col=target_col, primary_horizon=horizon,
        cross_sectional=cs_evidence, time_series=ts_evidence, underlying_control=underlying_control, robustness=robustness,
        temporal_alignment=temporal, bootstrap=bootstrap, placebo_results=placebo_results, affordability=affordability,
        liquidity=liquidity, cost_sensitivity=cost_sensitivity, outlier_trimmed_ic=outlier_trimmed_ic,
        bh_significant=None, bh_adjusted_p=None,
    )


@dataclass(frozen=True)
class Phase31Report:
    hypotheses: tuple[Hypothesis, ...]
    n_panel_rows: int
    underlyings: tuple[str, ...]
    evidence: dict[str, HypothesisEvidence]
    classifications: dict[str, tuple[DiscoveryClassification, str]]
    gates: dict[str, GateResult]
    multiple_testing: dict[str, object]


def run_campaign(
    store: InMemoryLeanSampleStore, *,
    max_contracts_per_underlying: int = DEFAULT_MAX_CONTRACTS_PER_UNDERLYING,
    n_placebo_trials: int = DEFAULT_N_PLACEBO_TRIALS, n_bootstrap_resamples: int = DEFAULT_N_BOOTSTRAP_RESAMPLES,
    hypothesis_registry_path: Path | None = None, preregistration_store_path: Path | None = None,
    min_universe_size: int = 3,
) -> Phase31Report:
    hypotheses = build_hypotheses()
    if hypothesis_registry_path is not None and preregistration_store_path is not None:
        registry = HypothesisRegistry(hypothesis_registry_path)
        prereg_store = PreregistrationStore(preregistration_store_path)
        hypotheses = register_all(registry, prereg_store)
        for h in hypotheses:
            require_preregistered(prereg_store, h.hypothesis_id, h.version)  # enforced BEFORE any evaluation below

    panel_rows = build_panel_rows(store, max_contracts_per_underlying=max_contracts_per_underlying)
    panel_rows = residualize_against_underlying(
        panel_rows, option_target_col=f"forward_option_return_{RESIDUALIZATION_HORIZON}",
        underlying_target_col=f"forward_underlying_return_{RESIDUALIZATION_HORIZON}",
    )

    raw_evidence: dict[str, HypothesisEvidence] = {
        h.hypothesis_id: evaluate_one_hypothesis(
            h, panel_rows, n_placebo_trials=n_placebo_trials, n_bootstrap_resamples=n_bootstrap_resamples,
            min_universe_size=min_universe_size,
        )
        for h in hypotheses
    }

    labeled_p = [
        (hid, ev.cross_sectional.report.ic_p_value if (ev.cross_sectional.applicable and ev.cross_sectional.report and ev.cross_sectional.report.ic_p_value is not None) else 1.0)
        for hid, ev in raw_evidence.items()
    ]
    mtc = multiple_testing_across_family(labeled_p)
    bh_by_id = {r.label: r for r in mtc["benjamini_hochberg"].results}

    final_evidence: dict[str, HypothesisEvidence] = {}
    for hid, ev in raw_evidence.items():
        bh = bh_by_id.get(hid)
        final_evidence[hid] = dataclasses.replace(
            ev, bh_significant=(bh.significant_at_alpha if bh else None), bh_adjusted_p=(bh.adjusted_p_value if bh else None),
        )

    classifications = {hid: classify_hypothesis(ev) for hid, ev in final_evidence.items()}
    gates = {hid: evaluate_gate(ev) for hid, ev in final_evidence.items()}

    return Phase31Report(
        hypotheses=hypotheses, n_panel_rows=len(panel_rows),
        underlyings=tuple(sorted({r["underlying_symbol"] for r in panel_rows})),
        evidence=final_evidence, classifications=classifications, gates=gates, multiple_testing=mtc,
    )
