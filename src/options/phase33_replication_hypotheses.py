"""Phase 33, Part D & I/24 — the preregistered `p22_opt013_coarse_replication`
hypothesis family: FIVE hypotheses, one feature
(`bucket_range_expansion_median`, Part C), five targets, evaluated and
reported SEPARATELY (Part D's explicit instruction: "kept clearly
separated... A positive MFE relationship alone is NOT a directional
trading strategy").

`P33-REPL-MFE` is the PRIMARY hypothesis -- faithful to P22-OPT-013's
own primary target (Phase 22/23's `mfe_5`, here `forward_bucket_mfe_5`,
Phase 32's already-built compounded-path maximum). The other four exist
because Part D requires evaluating MAE, MFE-MAE, absolute return, and
directional return too, but none of them inherits P22-OPT-013's own
directional expectation -- Phase 22/23 never established one for these
targets (Phase 23's own target-validation family found close-to-close
return targets A-E statistically indistinguishable from zero), so each
is preregistered `unsigned` rather than borrowing a claim the parent
result never made.

Reuses Phase 32's `MinimumSampleRequirements`/`MIN_SAMPLE` UNCHANGED
(Part E: "Use the EXACT Phase 32 validated bucket taxonomy... frozen
before evaluation" -- the sample-size floor is part of that same frozen
methodology) and Phase 4/7's `Hypothesis`/`HypothesisRegistry`/
`PreregistrationRecord`/`PreregistrationStore`, exactly as Phase 31 and
32 did.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.options.phase32_hypotheses import MIN_SAMPLE
from src.research.hypothesis import Hypothesis, HypothesisRegistry
from src.research.preregistration import PreregistrationRecord, PreregistrationStore

FAMILY = "p22_opt013_coarse_replication"
REGISTERED_AT = datetime(2026, 9, 4, tzinfo=timezone.utc)
FEATURE_COL = "bucket_range_expansion_median"
PRIMARY_HYPOTHESIS_ID = "P33-REPL-MFE"

# (id_suffix, name, target_col, direction, is_primary)
_DEFINITIONS: tuple[tuple[str, str, str, str, bool], ...] = (
    ("MFE", "Coarse-Grained Range Expansion -> Future MFE (PRIMARY, faithful to P22-OPT-013)", "forward_bucket_mfe_5", "positive", True),
    ("MAE", "Coarse-Grained Range Expansion -> Future MAE (secondary target, kept separate)", "forward_bucket_mae_5", "unsigned", False),
    ("SPREAD", "Coarse-Grained Range Expansion -> Future MFE-MAE Spread (mirrors Phase 23 Target H)", "bucket_mfe_minus_mae_5", "positive", False),
    ("ABS", "Coarse-Grained Range Expansion -> Future Absolute Bucket Return (secondary, non-directional)", "forward_abs_bucket_return_5", "unsigned", False),
    ("DIR", "Coarse-Grained Range Expansion -> Future Directional Bucket Return (secondary, directional; NOT a trading strategy on its own)", "forward_bucket_return_5", "unsigned", False),
)


def hypothesis_id(suffix: str) -> str:
    return f"P33-REPL-{suffix}"


IS_PRIMARY_BY_ID: dict[str, bool] = {hypothesis_id(suffix): is_primary for suffix, _name, _target, _direction, is_primary in _DEFINITIONS}


def build_hypotheses() -> tuple[Hypothesis, ...]:
    out = []
    for suffix, name, target, direction, is_primary in _DEFINITIONS:
        out.append(Hypothesis(
            hypothesis_id=hypothesis_id(suffix), name=name,
            description=f"{name}: does the coarse-grained bucket-level range-expansion feature "
                        f"{FEATURE_COL!r} (a bucket-day aggregate of the SAME causal per-contract "
                        f"`option_range_expansion` P22-OPT-013/P31-OPT-003 already use) predict "
                        f"{target!r} at a 5-day primary horizon?",
            economic_intuition="P22-OPT-013 found that an option's own recent range-expansion ratio predicts its "
                                "5-day forward maximum favorable excursion. If this is a genuine option-specific "
                                "relationship rather than an individual-contract sparsity artifact, it should "
                                "survive being expressed as a bucket-level aggregate.",
            expected_mechanism="A burst of unusually wide daily ranges across many contracts in the same economic "
                                "bucket may signal the start of a genuine volatility regime shift for that bucket, "
                                "analogous to the individual-contract mechanism Phase 23 partially attributed to the "
                                "option's own recent range level.",
            mathematical_definition=f"Cross-sectional, pooled time-series, DTE-balanced, moneyness-balanced, and "
                                     f"call/put-balanced relationship between {FEATURE_COL!r} (median of contract-level "
                                     f"option_range_expansion within the bucket-day, Part C) and {target!r} (Phase 32's "
                                     f"causal bucket-day forward target), on the frozen Phase 32 bucket taxonomy.",
            required_data=("FREE_REFERENCE_DATASET (Phase 26/27 real QuantConnect/Lean sample), bucketed via Phase 32's causal aggregation",),
            required_features=(FEATURE_COL,), prediction_horizon_bars=5,
            test_methodology="Pooled time-series, cross-sectional, DTE-balanced/moneyness-balanced/call-put-balanced "
                              "pooled relationships; underlying-only control; leave-one-symbol/period-out; "
                              "non-overlapping-window re-evaluation; outlier removal; placebo battery; real "
                              "expiration/year concentration reporting; multiple-testing correction across the full "
                              "registered test family.",
            expected_direction=direction,
            assumptions=("No delta is available in this dataset; no delta-scaled feature is fabricated.",
                         "Bucket membership at date t never depends on whether a contract is observed on any later date.",
                         "This hypothesis is a REPLICATION of P22-OPT-013 at a coarser grain, not a new discovery -- "
                         "its purpose is to determine whether the parent relationship survives, not to improve on it."),
            family=FAMILY, target_definition=target, holding_period_bars=5,
            universe=("AAPL", "FOXA", "GOOG", "NWSA", "TWX"),
            parent_hypothesis_id="P22-OPT-013",
            falsification_criteria=(
                f"The relationship on {FEATURE_COL!r} vs {target!r} fails to survive Benjamini-Hochberg correction "
                f"across the full registered test family.",
                "The relationship is fully explained by the underlying-only control (INHERITED_FROM_UNDERLYING).",
                "The relationship depends primarily on one symbol, one real expiration, one year, one moneyness "
                "bucket, one DTE bucket, one call/put side, or extreme outliers.",
                "The relationship does not survive non-overlapping-window re-evaluation.",
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
                "min_sample": {
                    "min_bucket_contracts": MIN_SAMPLE.min_bucket_contracts,
                    "min_bucket_series_dates": MIN_SAMPLE.min_bucket_series_dates,
                    "min_symbol_level_observations": MIN_SAMPLE.min_symbol_level_observations,
                    "min_pooled_observations": MIN_SAMPLE.min_pooled_observations,
                    "min_cross_sectional_peer_group": MIN_SAMPLE.min_cross_sectional_peer_group,
                },
                "is_primary": IS_PRIMARY_BY_ID[h.hypothesis_id],
            },
            validation_methodology=h.test_methodology,
            cost_assumptions="Real median bid/ask spread within the bucket as the execution-cost proxy; no commission "
                              "assumption beyond the $0/contract Robinhood-documented default used since Phase 30.",
            success_criteria=(
                "Survives Benjamini-Hochberg correction across the full registered test family.",
                "Underlying-control classification is not INHERITED_FROM_UNDERLYING.",
                "Survives non-overlapping-window re-evaluation, leave-one-symbol-out, and leave-one-period-out.",
                "Not dominated by a single real expiration, year, symbol, moneyness bucket, DTE bucket, or call/put side.",
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
