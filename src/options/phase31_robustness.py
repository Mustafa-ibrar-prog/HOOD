"""Phase 31, Parts 10, 11 & 13/18 — multiple testing, stratified
robustness, and the temporal-alignment shift test.

Part 12 (placebos) is deliberately NOT wrapped here: `src.research.
cross_sectional_placebo` (shuffled/shifted/random-feature/time-shuffled)
and `src.options.placebo_extensions` (within-symbol-time-shuffle,
symbol-identity-shuffle, block-preserving-shuffle, sign-flip diagnostic)
already return the exact same `CrossSectionalPlaceboResult` shape
uniformly — the campaign orchestrator (`phase31_campaign.py`) calls them
directly, since a wrapper here would add nothing but indirection.

Part 10 (multiple testing) is a thin re-export wrapper around
`src.research.multiple_testing`'s three correction functions (Bonferroni/
Holm/Benjamini-Hochberg, all already implemented) plus
`src.research.overfitting_metrics` (PBO/DSR/effective-trials) — reused,
not reimplemented.

Part 11 (robustness) is genuinely new: stratifies a hypothesis's
cross-sectional evidence by year/underlying/expiration/moneyness-bucket/
call-put and by leave-one-underlying-out, using
`phase31_evidence.evaluate_cross_sectional_evidence` per stratum (itself
already economically-scoped). A hypothesis is FRAGILE by this module's
definition if its sign flips across ANY stratification axis with >= 2
strata carrying a real IC.

Part 13 (temporal alignment) wraps `src.research.cross_sectional_placebo.
shifted_signal_placebo` at shifts +1/+2/+5/+10 (Part 13's exact list) —
NOTE: that function groups by `row["symbol"]` (this campaign sets
`symbol == underlying_symbol`), so this diagnostic operates at the
UNDERLYING level, not per-individual-contract — a real, disclosed
limitation of reusing the existing shift-placebo machinery rather than
writing a new per-contract shift test.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Sequence

from src.options.phase31_evidence import evaluate_cross_sectional_evidence
from src.research.cross_sectional_placebo import shifted_signal_placebo
from src.research.multiple_testing import (
    MultipleTestingReport,
    benjamini_hochberg_fdr,
    bonferroni_correction,
    holm_bonferroni_correction,
)
from src.research.overfitting_metrics import (
    DeflatedSharpeResult,
    EffectiveTrialsResult,
    PBOResult,
    deflated_sharpe_ratio,
    effective_number_of_trials,
    probability_of_backtest_overfitting,
)

DEFAULT_TEMPORAL_SHIFTS: tuple[int, ...] = (1, 2, 5, 10)


def multiple_testing_across_family(labeled_p_values: Sequence[tuple[str, float]], *, alpha: float = 0.05) -> dict[str, MultipleTestingReport]:
    return {
        "bonferroni": bonferroni_correction(labeled_p_values, alpha=alpha),
        "holm": holm_bonferroni_correction(labeled_p_values, alpha=alpha),
        "benjamini_hochberg": benjamini_hochberg_fdr(labeled_p_values, alpha=alpha),
    }


def family_effective_trials(ic_series_by_hypothesis: dict[str, list[float]]) -> EffectiveTrialsResult:
    variants = [v for v in ic_series_by_hypothesis.values() if v]
    return effective_number_of_trials(variants)


def family_pbo(returns_by_variant: Sequence[Sequence[float]], *, min_periods: int = 4) -> PBOResult:
    return probability_of_backtest_overfitting(returns_by_variant, min_periods=min_periods)


def family_deflated_sharpe(best_variant_returns: Sequence[float], *, n_trials: int) -> DeflatedSharpeResult:
    return deflated_sharpe_ratio(best_variant_returns, n_trials=n_trials)


@dataclass(frozen=True)
class StratumResult:
    stratum_name: str
    stratum_value: str
    n_rows: int
    average_ic: float | None


def _stratify_ic(
    panel_rows: Sequence[dict], *, feature_col: str, target_col: str, key_fn: Callable[[dict], object], min_universe_size: int = 3,
) -> tuple[StratumResult, ...]:
    groups: dict[object, list[dict]] = defaultdict(list)
    for r in panel_rows:
        groups[key_fn(r)].append(r)
    out = []
    for key in sorted(groups, key=str):
        rows = groups[key]
        evidence = evaluate_cross_sectional_evidence(rows, feature_col=feature_col, target_col=target_col, min_universe_size=min_universe_size)
        ic = evidence.report.ic_summary.average_ic if (evidence.applicable and evidence.report is not None) else None
        out.append(StratumResult(stratum_name=str(key), stratum_value=str(key), n_rows=len(rows), average_ic=ic))
    return tuple(out)


def _leave_one_underlying_out(panel_rows: Sequence[dict], *, feature_col: str, target_col: str, min_universe_size: int = 3) -> tuple[StratumResult, ...]:
    underlyings = sorted({r["underlying_symbol"] for r in panel_rows})
    out = []
    for u in underlyings:
        subset = [r for r in panel_rows if r["underlying_symbol"] != u]
        evidence = evaluate_cross_sectional_evidence(subset, feature_col=feature_col, target_col=target_col, min_universe_size=min_universe_size)
        ic = evidence.report.ic_summary.average_ic if (evidence.applicable and evidence.report is not None) else None
        out.append(StratumResult(stratum_name=f"excluding_{u}", stratum_value=u, n_rows=len(subset), average_ic=ic))
    return tuple(out)


def _sign_flips(results: tuple[StratumResult, ...]) -> bool:
    ics = [r.average_ic for r in results if r.average_ic is not None]
    if len(ics) < 2:
        return False
    return len({ic > 0 for ic in ics}) > 1


@dataclass(frozen=True)
class RobustnessReport:
    feature_col: str
    target_col: str
    by_year: tuple[StratumResult, ...]
    by_underlying: tuple[StratumResult, ...]
    by_expiration: tuple[StratumResult, ...]
    by_moneyness_bucket: tuple[StratumResult, ...]
    by_call_put: tuple[StratumResult, ...]
    leave_one_underlying_out: tuple[StratumResult, ...]
    sign_flips_across_years: bool
    sign_flips_across_underlyings: bool
    sign_flips_across_expirations: bool
    sign_flips_across_moneyness: bool
    sign_flips_call_vs_put: bool
    fragile: bool


def evaluate_robustness(panel_rows: Sequence[dict], *, feature_col: str, target_col: str, min_universe_size: int = 3) -> RobustnessReport:
    by_year = _stratify_ic(panel_rows, feature_col=feature_col, target_col=target_col, key_fn=lambda r: r["timestamp"].year, min_universe_size=min_universe_size)
    by_underlying = _stratify_ic(panel_rows, feature_col=feature_col, target_col=target_col, key_fn=lambda r: r["underlying_symbol"], min_universe_size=min_universe_size)
    by_expiration = _stratify_ic(panel_rows, feature_col=feature_col, target_col=target_col, key_fn=lambda r: r["expiration"], min_universe_size=min_universe_size)
    by_moneyness = _stratify_ic(panel_rows, feature_col=feature_col, target_col=target_col, key_fn=lambda r: r.get("moneyness_bucket"), min_universe_size=min_universe_size)
    by_call_put = _stratify_ic(panel_rows, feature_col=feature_col, target_col=target_col, key_fn=lambda r: r["call_put"], min_universe_size=min_universe_size)
    loo = _leave_one_underlying_out(panel_rows, feature_col=feature_col, target_col=target_col, min_universe_size=min_universe_size)

    flips_year = _sign_flips(by_year)
    flips_underlying = _sign_flips(by_underlying)
    flips_expiration = _sign_flips(by_expiration)
    flips_moneyness = _sign_flips(by_moneyness)
    flips_call_put = _sign_flips(by_call_put)

    return RobustnessReport(
        feature_col=feature_col, target_col=target_col, by_year=by_year, by_underlying=by_underlying,
        by_expiration=by_expiration, by_moneyness_bucket=by_moneyness, by_call_put=by_call_put,
        leave_one_underlying_out=loo, sign_flips_across_years=flips_year, sign_flips_across_underlyings=flips_underlying,
        sign_flips_across_expirations=flips_expiration, sign_flips_across_moneyness=flips_moneyness,
        sign_flips_call_vs_put=flips_call_put,
        fragile=any((flips_year, flips_underlying, flips_expiration, flips_moneyness, flips_call_put)),
    )


@dataclass(frozen=True)
class TemporalAlignmentResult:
    shift: int
    true_ic: float | None
    shifted_ic: float | None
    concern: bool


def evaluate_temporal_alignment(
    panel_rows: Sequence[dict], *, feature_col: str, target_col: str, shifts: tuple[int, ...] = DEFAULT_TEMPORAL_SHIFTS, min_universe_size: int = 3,
) -> tuple[TemporalAlignmentResult, ...]:
    true_evidence = evaluate_cross_sectional_evidence(panel_rows, feature_col=feature_col, target_col=target_col, min_universe_size=min_universe_size)
    true_ic = true_evidence.report.ic_summary.average_ic if (true_evidence.applicable and true_evidence.report is not None) else None

    out = []
    for shift in shifts:
        result = shifted_signal_placebo(panel_rows, feature_col=feature_col, target_col=target_col, shift_bars=shift, min_universe_size=min_universe_size)
        shifted_ic = result.placebo_distribution[0] if result.placebo_distribution else None
        concern = true_ic is not None and shifted_ic is not None and abs(shifted_ic) >= abs(true_ic)
        out.append(TemporalAlignmentResult(shift=shift, true_ic=true_ic, shifted_ic=shifted_ic, concern=concern))
    return tuple(out)
