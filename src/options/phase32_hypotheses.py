"""Phase 32, Parts 1 (feature family) & 7/21 — the preregistered
`bucketed_options_alpha` hypothesis family and minimum-sample
requirements.

Reuses Phase 4/7's `Hypothesis`/`HypothesisRegistry`/
`PreregistrationRecord`/`PreregistrationStore` exactly as Phase 31 did —
same append-only, no-retroactive-edit discipline. A NEW family, not a
reuse of any Phase 31 hypothesis: every (feature, target) pair here
operates on `phase32_bucket_panel.py`'s bucket-day rows, a genuinely
different unit of analysis, and none of these 14 hypotheses is a
Phase 31 hypothesis merely relabeled (Part -- explicit prompt
instruction: "Do NOT reuse a Phase 31 hypothesis merely because it
looked promising" -- none of Phase 31's 16 were even classified as
promising, so there was nothing to carry over regardless).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from src.research.hypothesis import Hypothesis, HypothesisRegistry
from src.research.preregistration import PreregistrationRecord, PreregistrationStore

FAMILY = "bucketed_options_alpha"
REGISTERED_AT = datetime(2026, 9, 4, tzinfo=timezone.utc)


@dataclass(frozen=True)
class MinimumSampleRequirements:
    """Part 7 — fixed BEFORE any bucket result was computed."""

    min_bucket_contracts: int = 3          # a bucket-day must aggregate >= this many real contracts to be usable at all
    min_bucket_series_dates: int = 10      # a bucket SERIES needs >= this many real dates for a feature/target relationship
    min_symbol_level_observations: int = 15  # a per-underlying evaluation needs >= this many bucket-date rows
    min_pooled_observations: int = 30      # a pooled (all underlyings) evaluation needs >= this many rows
    min_cross_sectional_peer_group: int = 3  # a same-date cross-sectional peer group needs >= this many buckets present


MIN_SAMPLE = MinimumSampleRequirements()

# (id_suffix, name, feature_col, target_col, horizon_days, expected_direction, family_letter, intuition, mechanism)
_DEFINITIONS: tuple[tuple[str, str, str, str, int, str, str, str, str], ...] = (
    ("001", "Bucket Momentum", "bucket_median_return", "forward_bucket_return_5", 5, "positive", "A",
     "A bucket's own recent median return may predict its return over the next several real bucket-dates (aggregate momentum).",
     "Aggregate order-flow/information absorption across many contracts in the same economic bucket persists over several days."),
    ("002", "Bucket Short-Horizon Reversal", "bucket_median_return", "forward_bucket_return_1", 1, "negative", "A",
     "An unusually large bucket-median return today may partially reverse the very next real bucket-date.",
     "A large one-day aggregate move often reflects transient liquidity/quote effects that partially unwind quickly."),
    ("003", "Bucket Dispersion Persistence", "bucket_return_dispersion", "forward_dispersion_5", 5, "positive", "A",
     "A bucket's current cross-sectional return dispersion may predict its future dispersion (volatility-of-dispersion clustering).",
     "Cross-sectional dispersion across contracts in a bucket is itself a volatility-like quantity and may cluster like realized volatility does."),
    ("004", "Positive-Return-Fraction Persistence", "bucket_positive_return_fraction", "forward_bucket_return_5", 5, "positive", "A",
     "A bucket where most contracts moved up today may continue outperforming.",
     "A high positive-return fraction reflects broad-based (not single-contract-driven) strength, which may be more persistent than an idiosyncratic move."),
    ("005", "Extreme-Return-Fraction -> Range Expansion", "bucket_extreme_return_fraction", "forward_range_expansion_ratio_5", 5, "positive", "A",
     "A bucket with an unusually large fraction of extreme-moving contracts today may see elevated dispersion over the next several dates.",
     "A burst of extreme contract-level moves may signal the start of a genuine volatility regime shift for the whole bucket."),
    ("006", "Call/Put Return Spread Persistence", "call_put_return_spread", "forward_bucket_return_5", 5, "positive", "B",
     "A positive call-vs-put return spread today (calls outperforming puts in the same DTE/moneyness/underlying/date bucket) may predict continued relative call strength.",
     "Structural demand imbalances between calls and puts (e.g. hedging flow) can persist over several days."),
    ("007", "Call/Put Dispersion Diff -> Future Dispersion", "call_put_dispersion_diff", "forward_dispersion_5", 5, "unsigned", "B",
     "A difference in call vs put cross-sectional dispersion today may carry information about future bucket-level dispersion.",
     "Calls and puts can carry systematically different dispersion profiles that persist into near-term future dispersion."),
    ("008", "Moneyness Slope Persistence", "moneyness_slope", "forward_bucket_return_underlying_adjusted_5", 5, "unsigned", "C",
     "The cross-moneyness slope of returns (how return varies from deep-ITM to deep-OTM) may predict underlying-adjusted forward bucket return.",
     "A skew in how far-OTM vs far-ITM contracts are moving may reflect information not captured by the underlying's own return alone."),
    ("009", "OTM-ATM Spread Reversal", "otm_atm_spread", "forward_bucket_return_5", 5, "negative", "C",
     "An unusually large OTM-vs-ATM return spread today may mean-revert.",
     "OTM contracts' extra leverage can produce transient overreactions relative to ATM contracts that partially unwind."),
    ("010", "DTE Slope Persistence", "dte_slope", "forward_bucket_return_underlying_adjusted_5", 5, "unsigned", "D",
     "The cross-DTE slope of returns (how return varies from short- to long-dated) may predict underlying-adjusted forward bucket return.",
     "Term-structure-like effects in option returns may carry predictive content beyond the underlying's own move."),
    ("011", "Short-Medium DTE Spread -> Future Return", "short_medium_dte_spread", "forward_bucket_return_5", 5, "unsigned", "D",
     "A spread between short- and medium-DTE bucket returns today may predict the medium-DTE bucket's own forward return.",
     "Divergent short vs medium-DTE behavior may reflect information not yet reflected in the medium-DTE bucket's own price."),
    ("012", "Option-Minus-Underlying Return Reversal", "option_minus_underlying_return", "forward_bucket_return_underlying_adjusted_5", 5, "negative", "E",
     "A bucket's return diverging strongly from its underlying's own same-day return today may partially reverse (relative to the underlying) over the next several dates.",
     "A same-day divergence between aggregate option behavior and the underlying often reflects a transient quote/liquidity artifact that should partially unwind."),
    ("013", "Dispersion-vs-Underlying-Vol -> Future MFE", "dispersion_minus_underlying_vol", "forward_bucket_mfe_5", 5, "positive", "E",
     "A bucket whose cross-sectional dispersion currently exceeds the underlying's own realized volatility may see a higher subsequent maximum favorable excursion.",
     "Dispersion in excess of what the underlying's own volatility would imply may signal genuine option-specific opportunity, expressed here as MFE, not direction."),
    ("014", "Cross-Sectional Range -> Future Absolute Return", "bucket_cross_sectional_range", "forward_abs_bucket_return_5", 5, "positive", "A",
     "A bucket with a wide cross-sectional range of contract returns today may see larger absolute bucket-level moves going forward.",
     "A wide current range reflects genuine within-bucket heterogeneity/uncertainty, which may persist as larger future magnitude moves."),
)


def hypothesis_id(suffix: str) -> str:
    return f"P32-BKT-{suffix}"


def build_hypotheses() -> tuple[Hypothesis, ...]:
    out = []
    for suffix, name, feature, target, horizon, direction, letter, intuition, mechanism in _DEFINITIONS:
        out.append(Hypothesis(
            hypothesis_id=hypothesis_id(suffix), name=name,
            description=f"{name} (Part 4{letter}): does bucket feature {feature!r} predict {target!r} at a {horizon}-day primary horizon?",
            economic_intuition=intuition, expected_mechanism=mechanism,
            mathematical_definition=f"Cross-sectional and per-bucket-series time-series relationship between bucket "
                                     f"feature {feature!r} and forward bucket target {target!r}, computed on causally-"
                                     f"constructed bucket-day aggregates (no future-survival membership).",
            required_data=("FREE_REFERENCE_DATASET (Phase 26/27 real QuantConnect/Lean sample), bucketed via Phase 32's causal aggregation",),
            required_features=(feature,), prediction_horizon_bars=horizon,
            test_methodology="Pooled time-series, cross-sectional (same real date across buckets), per-symbol, and "
                              "symbol-balanced pooled relationships; underlying-only control; multiple-testing "
                              "correction; placebo battery; leave-one-symbol/period-out robustness; affordability/cost reporting.",
            expected_direction=direction,
            assumptions=("No delta is available in this dataset; no delta-scaled feature is fabricated.",
                         "Bucket membership at date t never depends on whether a contract is observed on any later date."),
            family=FAMILY, target_definition=target, holding_period_bars=horizon,
            universe=("AAPL", "FOXA", "GOOG", "NWSA", "TWX"),
            falsification_criteria=(
                f"Pooled relationship on {feature!r} vs {target!r} fails to survive Benjamini-Hochberg correction across the full 14-hypothesis family.",
                "The relationship is fully explained by the underlying-only control.",
                "The relationship does not survive leave-one-symbol-out or leave-one-period-out perturbation.",
            ),
            created_at=REGISTERED_AT,
        ))
    return tuple(out)


def build_preregistrations(hypotheses: tuple[Hypothesis, ...]) -> tuple[PreregistrationRecord, ...]:
    out = []
    for h in hypotheses:
        out.append(PreregistrationRecord(
            hypothesis_id=h.hypothesis_id, hypothesis_version=h.version, rationale=h.economic_intuition,
            expected_direction=h.expected_direction, target_definition=h.target_definition,
            features=h.required_features, universe_name="bucketed_free_reference_dataset",
            time_horizon_bars=h.prediction_horizon_bars,
            parameter_ranges={
                "secondary_horizons_days": [1, 3, 5, 10, 20],
                "min_sample": {
                    "min_bucket_contracts": MIN_SAMPLE.min_bucket_contracts,
                    "min_bucket_series_dates": MIN_SAMPLE.min_bucket_series_dates,
                    "min_symbol_level_observations": MIN_SAMPLE.min_symbol_level_observations,
                    "min_pooled_observations": MIN_SAMPLE.min_pooled_observations,
                    "min_cross_sectional_peer_group": MIN_SAMPLE.min_cross_sectional_peer_group,
                },
            },
            validation_methodology=h.test_methodology,
            cost_assumptions="Real median bid/ask spread within the bucket as the execution-cost proxy; no commission "
                              "assumption beyond the $0/contract Robinhood-documented default used since Phase 30.",
            success_criteria=(
                "Survives Benjamini-Hochberg correction across the full family.",
                "Underlying-control classification is OPTION_ADDS_INFORMATION, not INHERITED_FROM_UNDERLYING.",
                "Survives leave-one-symbol-out and leave-one-period-out perturbation.",
                "Meets every minimum-sample requirement in MinimumSampleRequirements.",
            ),
            falsification_criteria=h.falsification_criteria,
            registered_at=REGISTERED_AT,
        ))
    return tuple(out)


def register_all(registry: HypothesisRegistry, prereg_store: PreregistrationStore) -> tuple[Hypothesis, ...]:
    hypotheses = build_hypotheses()
    preregs = build_preregistrations(hypotheses)
    for h in hypotheses:
        if registry.get(h.hypothesis_id) is None:
            registry.register(h)
    for p in preregs:
        if prereg_store.get(p.hypothesis_id, p.hypothesis_version) is None:
            prereg_store.register(p)
    return hypotheses
