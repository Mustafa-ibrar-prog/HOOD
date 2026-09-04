"""Phase 31, Part 14/18 — the discovery classification.

Every hypothesis receives EXACTLY one of the 7 required labels, decided
by EXPLICIT, DOCUMENTED numeric criteria (Part 14: "Do not classify
something as supported simply because p < 0.05") -- never a bare
significance check. `HypothesisEvidence` is the consolidated bundle every
other Phase 31 module's output feeds into; `classify_hypothesis` reads
only that bundle, never re-touches raw panel data. The small helper
functions below (`average_ic`, `n_timestamps`, `quantile_spread`,
`bootstrap_excludes_zero`, `placebo_separates`, `outlier_dependent`) are
PUBLIC (not `_`-prefixed) specifically so `phase31_gate.py`'s Promising
Finding Gate can reuse the exact same criteria this module uses, rather
than recomputing them a second way (the established convention set by
`src.options.placebo_extensions`'s docstring: a module that deliberately
does NOT export a private helper gets its own local copy; here the
opposite choice is made deliberately, since gate.py must apply
IDENTICAL criteria, not an independently-reimplemented approximation).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from src.options.dependence_bootstrap import SymbolClusterBootstrapReport
from src.options.mechanical_baseline import BaselineClassification
from src.options.phase31_affordability_liquidity import AffordabilityFilterReport, CostSensitivityResult, LiquidityReport
from src.options.phase31_evidence import CrossSectionalEvidence, TimeSeriesEvidence
from src.options.phase31_robustness import RobustnessReport, TemporalAlignmentResult
from src.research.cross_sectional_placebo import CrossSectionalPlaceboResult

# Thresholds, fixed BEFORE any hypothesis's result was seen (Part 14/15 discipline).
MIN_TIMESTAMPS_FOR_POWER = 10
MATERIAL_IC_THRESHOLD = 0.01
MATERIAL_QUANTILE_SPREAD = 0.005
PLACEBO_EMPIRICAL_P_THRESHOLD = 0.10
OUTLIER_TOLERANCE_FRACTION = 0.5  # trimmed IC may lose at most 50% of its magnitude before being outlier-dependent


class DiscoveryClassification(enum.Enum):
    DISCOVERY_SUPPORTED = "discovery_supported"
    PROMISING = "promising"
    INCONCLUSIVE = "inconclusive"
    FRAGILE = "fragile"
    REJECTED = "rejected"
    INHERITED_FROM_UNDERLYING = "inherited_from_underlying"
    NOT_READY = "not_ready"


@dataclass(frozen=True)
class HypothesisEvidence:
    hypothesis_id: str
    feature_col: str
    target_col: str
    primary_horizon: int
    cross_sectional: CrossSectionalEvidence
    time_series: TimeSeriesEvidence
    underlying_control: object | None  # phase31_underlying_control.UnderlyingControlReport | None
    robustness: RobustnessReport
    temporal_alignment: tuple[TemporalAlignmentResult, ...]
    bootstrap: SymbolClusterBootstrapReport | None
    placebo_results: dict[str, CrossSectionalPlaceboResult]
    affordability: AffordabilityFilterReport
    liquidity: LiquidityReport
    cost_sensitivity: tuple[CostSensitivityResult, ...]
    outlier_trimmed_ic: float | None
    bh_significant: bool | None
    bh_adjusted_p: float | None


def average_ic(evidence: CrossSectionalEvidence) -> float | None:
    if evidence.applicable and evidence.report is not None:
        return evidence.report.ic_summary.average_ic
    return None


def n_timestamps(evidence: CrossSectionalEvidence) -> int:
    if evidence.applicable and evidence.report is not None:
        return sum(1 for p in evidence.report.ic_summary.points if p.ic is not None)
    return 0


def quantile_spread(evidence: CrossSectionalEvidence) -> float | None:
    if evidence.applicable and evidence.report is not None:
        return evidence.report.quantile_report.spread_q5_minus_q1
    return None


def bootstrap_excludes_zero(bootstrap: SymbolClusterBootstrapReport | None) -> bool:
    if bootstrap is None or bootstrap.lower_bound is None or bootstrap.upper_bound is None:
        return False
    return not (bootstrap.lower_bound <= 0 <= bootstrap.upper_bound)


def placebo_separates(placebo_results: dict[str, CrossSectionalPlaceboResult]) -> bool:
    shuffled = placebo_results.get("shuffled_signal_placebo")
    if shuffled is None or shuffled.empirical_p_value is None:
        return False
    return shuffled.empirical_p_value < PLACEBO_EMPIRICAL_P_THRESHOLD


def outlier_dependent(evidence: HypothesisEvidence, ic_value: float | None) -> bool:
    if ic_value is None or evidence.outlier_trimmed_ic is None:
        return False  # cannot evaluate -- never assumed dependent by default
    if abs(ic_value) < 1e-9:
        return False
    ratio = evidence.outlier_trimmed_ic / ic_value
    return ratio < OUTLIER_TOLERANCE_FRACTION or (ic_value > 0) != (evidence.outlier_trimmed_ic > 0)


def classify_hypothesis(evidence: HypothesisEvidence) -> tuple[DiscoveryClassification, str]:
    cs = evidence.cross_sectional
    ic_value = average_ic(cs)
    n_ts = n_timestamps(cs)
    spread_value = quantile_spread(cs)

    if not cs.applicable and not evidence.time_series.applicable:
        return DiscoveryClassification.NOT_READY, (
            f"Neither cross-sectional ({cs.reason}) nor time-series ({evidence.time_series.reason}) evidence "
            "could even be computed for this hypothesis's real data -- no test was possible."
        )

    if ic_value is None or n_ts < MIN_TIMESTAMPS_FOR_POWER:
        return DiscoveryClassification.INCONCLUSIVE, (
            f"Cross-sectional IC is undefined or based on only {n_ts} timestamps "
            f"(need >= {MIN_TIMESTAMPS_FOR_POWER}) -- underpowered, not clearly rejected or supported."
        )

    adds_info = (
        evidence.underlying_control is not None
        and getattr(evidence.underlying_control, "classification", None) == BaselineClassification.OPTION_ADDS_INFORMATION
    )
    placebo_sep = placebo_separates(evidence.placebo_results)
    bh_sig = evidence.bh_significant is True

    if abs(ic_value) < MATERIAL_IC_THRESHOLD and not bh_sig and not placebo_sep:
        return DiscoveryClassification.REJECTED, (
            f"Pooled cross-sectional IC ({ic_value:.4f}) is below the material threshold "
            f"({MATERIAL_IC_THRESHOLD}), not BH-significant, and the shuffled-signal placebo does not separate "
            "the observed statistic from chance."
        )

    if not adds_info:
        return DiscoveryClassification.INHERITED_FROM_UNDERLYING, (
            f"Underlying-only control classifies this relationship as "
            f"{getattr(evidence.underlying_control, 'classification', 'BOTH_WEAK_OR_UNDEFINED')} -- the option "
            "feature does not exceed what the underlying's own forward return already explains."
        )

    robust = not evidence.robustness.fragile
    temporal_concern = any(t.concern for t in evidence.temporal_alignment)
    bootstrap_ok = bootstrap_excludes_zero(evidence.bootstrap)
    outlier_dep = outlier_dependent(evidence, ic_value)
    cost_survives_1x = bool(evidence.cost_sensitivity) and evidence.cost_sensitivity[0].survives is True
    economically_meaningful = spread_value is not None and abs(spread_value) >= MATERIAL_QUANTILE_SPREAD

    if not robust or temporal_concern or not bootstrap_ok or outlier_dep:
        reasons = []
        if not robust:
            reasons.append("sign flips across a real stratification axis (year/underlying/expiration/moneyness/call-put)")
        if temporal_concern:
            reasons.append("a shifted (deliberately misaligned) relationship is at least as strong as the true one")
        if not bootstrap_ok:
            reasons.append("symbol-cluster bootstrap confidence interval includes zero")
        if outlier_dep:
            reasons.append("result depends heavily on outlier observations")
        return DiscoveryClassification.FRAGILE, "Adds information beyond the underlying, but: " + "; ".join(reasons) + "."

    if bh_sig and placebo_sep and bootstrap_ok and cost_survives_1x and economically_meaningful:
        return DiscoveryClassification.DISCOVERY_SUPPORTED, (
            f"IC={ic_value:.4f}, BH-significant, placebo-separated, bootstrap excludes zero, survives 1x cost, "
            f"quantile spread {spread_value} exceeds the material threshold, and robust across all "
            "stratification axes tested."
        )

    if bh_sig or placebo_sep:
        missing = []
        if not cost_survives_1x:
            missing.append("does not clearly survive 1x execution cost")
        if not economically_meaningful:
            missing.append("quantile spread below the material-significance threshold")
        return DiscoveryClassification.PROMISING, (
            f"IC={ic_value:.4f}, adds information beyond the underlying, robust across strata, but " + "; ".join(missing or ["borderline on one gate criterion"]) + "."
        )

    return DiscoveryClassification.INCONCLUSIVE, (
        f"IC={ic_value:.4f} is not BH-significant and the placebo battery does not clearly separate it from chance."
    )
