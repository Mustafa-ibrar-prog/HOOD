"""Phase 31, Part 1/18 — the `options_alpha_round2` preregistered
hypothesis family.

Reuses Phase 4/7's existing `Hypothesis`/`HypothesisRegistry`/
`PreregistrationRecord`/`PreregistrationStore` machinery directly
(`src.research.hypothesis`, `src.research.preregistration`) — the same
append-only, no-retroactive-edit discipline every prior research phase
in this codebase has used, not a parallel scheme.

This is a NEW family, genuinely distinct from Phase 19-23's
`options_alpha`/`options_alpha_replication`/`options_specific_alpha`
families: it runs against the FREE_REFERENCE_DATASET (Phase 26/27/30's
real QuantConnect/Lean sample: AAPL, FOXA, GOOG, NWSA, SPY, TWX) via
Phase 31's new `phase31_panel_builder.py` adapter, not the legacy
2021-2023 MCP-probe panel Phase 19-23 used. No hypothesis here retests a
Phase 19-23 `INHERITED_FROM_UNDERLYING`/`REJECTED` finding verbatim —
every (feature, target, horizon) combination below is new, chosen from
the prompt's 16 named families, and every hypothesis is registered
BEFORE any evaluation touches real data (Part 1's explicit requirement,
enforced structurally by `require_preregistered` — see
`phase31_campaign.py`).

PRIMARY HORIZON, PREREGISTERED (Part 4's explicit instruction: "the
primary horizon must be preregistered... do NOT optimize around whichever
horizon happens to produce the strongest result"): every hypothesis
below states its horizon in `prediction_horizon_bars` before any
evaluation; Part 4's other horizons (1/3/5/10/20 days) are still
evaluated for every hypothesis as SECONDARY evidence (see
`phase31_campaign.py`), but only the preregistered horizon's result may
ever be cited as the hypothesis's primary finding.

"_residualized" targets (used by hypotheses 6, 7, 10, 13) are Part 7's
causal `OPTION_RETURN ~ UNDERLYING_RETURN` residual, built by
`phase31_underlying_control.residualize_against_underlying` BEFORE these
hypotheses are evaluated — never fabricated, never presented as an
observed return.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.research.hypothesis import Hypothesis, HypothesisRegistry
from src.research.preregistration import PreregistrationRecord, PreregistrationStore

FAMILY = "options_alpha_round2"
UNIVERSE = ("AAPL", "FOXA", "GOOG", "NWSA", "SPY", "TWX")  # the real free dataset's 6 real underlyings (Phase 30)

REGISTERED_AT = datetime(2026, 9, 4, tzinfo=timezone.utc)

# (id_suffix, name, feature_col, target_col, horizon_days, expected_direction, economic_intuition, mechanism)
_DEFINITIONS: tuple[tuple[str, str, str, str, int, str, str, str], ...] = (
    ("001", "Option Momentum",
     "option_momentum", "forward_option_return_5", 5, "positive",
     "Recent option-specific price movement (a multi-day rolling return) may reflect information flow "
     "not yet fully absorbed into the option's price, predicting continuation.",
     "Option-specific order flow / demand imbalance persists over several days before fully resolving."),
    ("002", "Option Mean Reversion",
     "option_mean_reversion", "forward_option_return_5", 5, "negative",
     "An option trading unusually far from its own recent rolling mean may be overextended and prone to "
     "reverting toward that mean.",
     "Transient liquidity/order-flow shocks in a thinly-traded option push price away from a local "
     "equilibrium that later reasserts itself."),
    ("003", "Range Expansion",
     "option_range_expansion", "mfe_5", 5, "positive",
     "A contract whose own high-low range has recently expanded relative to its trailing average may be "
     "entering a higher-volatility regime, raising the favorable-excursion ceiling over the next few days.",
     "Volatility clusters; a recent real range expansion is informative about near-term realized "
     "volatility, which mechanically raises MFE."),
    ("004", "Range Compression",
     "option_recent_range_pct", "abs_forward_option_return_5", 5, "negative",
     "An option in an unusually COMPRESSED recent range may be building toward a larger subsequent move "
     "(the options-market analogue of a coiled-spring pattern).",
     "Compressed recent trading ranges often precede volatility expansion once whatever suppressed "
     "movement (illiquidity, an approaching catalyst) resolves."),
    ("005", "Relative Option Strength",
     "relative_option_strength", "forward_option_return_5", 5, "positive",
     "A contract that recently outperformed its economically-comparable peers (same underlying, same "
     "expiration, same real timestamp) may continue to do so.",
     "A contract-specific information or liquidity edge within a peer group persists over several days."),
    ("006", "Maturity Effects",
     "dte", "forward_option_return_5_residualized", 5, "unsigned",
     "Days-to-expiration may predict option-specific returns even AFTER controlling for the underlying's "
     "own forward movement (theta/gamma decay dynamics differ by DTE).",
     "Time decay and gamma exposure vary systematically with DTE, independent of the underlying's own "
     "path."),
    ("007", "Moneyness Effects",
     "log_moneyness", "forward_option_return_5_residualized", 5, "unsigned",
     "Log-moneyness may predict option-specific excess return after controlling for the underlying's own "
     "forward movement (distinct from simply being a leveraged bet on the underlying).",
     "Convexity/leverage differs by moneyness in a way not fully captured by a linear underlying-return "
     "control."),
    ("008", "Call/Put Asymmetry",
     "call_put_numeric", "forward_option_return_5_residualized", 5, "unsigned",
     "Calls and puts may behave differently even after controlling for the underlying's own direction and "
     "magnitude of movement.",
     "Structural demand imbalances (e.g. hedging flow) differ between calls and puts independent of "
     "realized underlying direction."),
    ("009", "Option/Underlying Divergence",
     "option_underlying_divergence", "forward_option_return_1", 1, "negative",
     "An option that moved unusually far from what its underlying's own same-day move would suggest may "
     "revert the next day.",
     "A same-day divergence between an option and its underlying often reflects a transient "
     "liquidity/quote artifact rather than new information, and should partially unwind quickly."),
    ("010", "Convexity Response",
     "convexity_proxy", "forward_option_return_5_residualized", 5, "positive",
     "The squared underlying daily return (a convexity/gamma-exposure proxy) may predict residual "
     "option-specific return beyond a purely linear underlying-return relationship.",
     "Option payoffs are convex in the underlying; a large realized move (regardless of sign) changes an "
     "option's effective delta/gamma profile in a way a single linear control does not capture."),
    ("011", "Contract Relative Value",
     "relative_price_rank", "forward_option_return_5", 5, "negative",
     "Within the same underlying/expiration/timestamp peer group, a contract trading RICH relative to "
     "peers (high relative_price_rank) may subsequently underperform, and a CHEAP one may outperform.",
     "Peer-relative mispricing within an economically comparable contract set mean-reverts as it is "
     "arbitraged or re-rated."),
    ("012", "Liquidity/Price Interaction",
     "spread_pct", "forward_option_return_5", 5, "negative",
     "A wider relative bid/ask spread may predict a worse forward realized return once real execution "
     "cost/adverse-selection effects are considered.",
     "Wide spreads reflect thin liquidity and higher effective transaction costs, both of which bias "
     "realized forward performance downward."),
    ("013", "DTE x Moneyness Interaction",
     "moneyness_x_dte_interaction", "forward_option_return_5_residualized", 5, "unsigned",
     "The interaction of moneyness and DTE (not either alone) may carry residual predictive content -- "
     "e.g. a moneyness effect that only appears at long or short DTE.",
     "Gamma/theta exposure is jointly determined by DTE and moneyness, not additively separable."),
    ("014", "Expiration Proximity",
     "inverse_dte", "abs_forward_option_return_5", 5, "positive",
     "As expiration approaches (DTE shrinks toward zero), an option's own relative price movement may "
     "become systematically larger (gamma risk intensifies near expiration).",
     "Gamma scales roughly with 1/sqrt(time-to-expiration); options close to expiration are mechanically "
     "more reactive to the same-sized underlying move."),
    ("015", "Option Volatility Persistence",
     "option_rolling_vol", "forward_realized_vol_5", 5, "positive",
     "An option's own recent realized volatility may predict its near-term future realized volatility.",
     "Volatility clustering is a well-documented, general market phenomenon; this hypothesis asks whether "
     "it holds at the OPTION-price level specifically, not just the underlying's."),
    ("016", "Option Shock Reversal",
     "option_daily_return", "forward_option_return_1", 1, "negative",
     "An extreme option-specific single-day price shock may partially reverse the next day.",
     "Large single-day option moves are frequently driven by transient illiquidity/order-flow effects that "
     "partially unwind once normal two-sided quoting resumes."),
)


def hypothesis_id(suffix: str) -> str:
    return f"P31-OPT-{suffix}"


def build_hypotheses() -> tuple[Hypothesis, ...]:
    out = []
    for suffix, name, feature, target, horizon, direction, intuition, mechanism in _DEFINITIONS:
        out.append(Hypothesis(
            hypothesis_id=hypothesis_id(suffix), name=name,
            description=f"{name}: does {feature!r} predict {target!r} at a {horizon}-day primary horizon?",
            economic_intuition=intuition, expected_mechanism=mechanism,
            mathematical_definition=f"Spearman rank IC and OLS relationship between panel column {feature!r} "
                                     f"and panel column {target!r}, evaluated both cross-sectionally (within "
                                     f"same underlying/expiration/timestamp peer groups) and within-contract "
                                     f"time-series.",
            required_data=("FREE_REFERENCE_DATASET (Phase 26/27 real QuantConnect/Lean sample)",),
            required_features=(feature,), prediction_horizon_bars=horizon,
            test_methodology="Cross-sectional IC/quantile spread + within-contract time-series correlation, "
                              "underlying-only control (Model A vs Model B), multiple-testing correction, "
                              "placebo battery, symbol/expiration/year-cluster bootstrap, temporal-alignment "
                              "shift test, affordability/liquidity/cost reporting.",
            expected_direction=direction,
            assumptions=("Free dataset's real bid/ask/OHLC are the only price source used; no fabricated field.",
                         "No native IV/Greeks exist in this dataset -- none used unless explicitly RECONSTRUCTED_IV-labeled."),
            family=FAMILY, target_definition=target, holding_period_bars=horizon,
            universe=UNIVERSE,
            falsification_criteria=(
                f"Pooled cross-sectional IC on {feature!r} vs {target!r} fails to survive Benjamini-Hochberg "
                "correction across the full 16-hypothesis family.",
                "The relationship is fully explained by the underlying-only control (gap <= material threshold).",
                "The relationship does not survive a symbol-cluster bootstrap at the 90% confidence level.",
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
            features=h.required_features, universe_name="free_reference_dataset_daily_subsample",
            time_horizon_bars=h.prediction_horizon_bars,
            parameter_ranges={"secondary_horizons_days": [1, 3, 5, 10, 20]},
            validation_methodology=h.test_methodology,
            cost_assumptions="Real bid/ask spread as the execution-cost proxy; no commission assumption beyond "
                              "Phase 30's $0/contract Robinhood-documented default.",
            success_criteria=(
                "Survives Benjamini-Hochberg correction across the full family.",
                "Underlying-control gap exceeds the 0.01 material-gap threshold (src.options.mechanical_baseline).",
                "Symbol-cluster bootstrap 90% CI excludes zero.",
                "Sign-stable across at least 4 of the 6 real underlyings with sufficient data.",
            ),
            falsification_criteria=h.falsification_criteria,
            registered_at=REGISTERED_AT,
        ))
    return tuple(out)


def register_all(registry: HypothesisRegistry, prereg_store: PreregistrationStore) -> tuple[Hypothesis, ...]:
    """Idempotent-friendly: skips a hypothesis_id that's already
    registered (so re-running the campaign script doesn't raise) rather
    than silently re-registering — the append-only store itself would
    reject a duplicate anyway; this just makes the caller's flow
    explicit."""
    hypotheses = build_hypotheses()
    preregs = build_preregistrations(hypotheses)
    for h in hypotheses:
        if registry.get(h.hypothesis_id) is None:
            registry.register(h)
    for p in preregs:
        if prereg_store.get(p.hypothesis_id, p.hypothesis_version) is None:
            prereg_store.register(p)
    return hypotheses
