"""Phase 30, Part 11/17 — the permanent free-data limitations registry.

The user has decided NOT to purchase ORATS or any paid provider
(Phase 29's `ORATS_ACTIVATION_PENDING_HUMAN` final state, unchanged) and
to accept `HISTORICAL_OPTIONS_DATA_PARTIAL` (Phase 27's
`EXPANDED_FINAL_GATE`) as a PERMANENT characteristic of this research
platform, not a defect awaiting a future fix. Every record below is a
REAL, already-established finding from Phase 26/27/29 (re-stated here as
a single, queryable registry, not re-derived) -- `permanent=True` on
every one reflects that decision, not an assumption this phase invents.

Part 11's explicit requirement -- "every future research report must
automatically include this" -- is satisfied by
`attach_limitations_disclosure()`: any report body a future module
produces is wrapped with the full registry attached, rather than relying
on every future report author to remember to cite it manually.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class LimitationCategory(enum.Enum):
    MISSING_UNDERLYINGS = "missing_underlyings"
    MISSING_YEARS = "missing_years"
    NO_NATIVE_IV = "no_native_iv"
    NO_NATIVE_GREEKS = "no_native_greeks"
    VOLUME_LIMITATIONS = "volume_limitations"
    OPEN_INTEREST_LIMITATIONS = "open_interest_limitations"
    QUOTE_LIMITATIONS = "quote_limitations"
    CORPORATE_ACTION_LIMITATIONS = "corporate_action_limitations"
    CONTRACT_LIFECYCLE_LIMITATIONS = "contract_lifecycle_limitations"
    SURVIVORSHIP_CONCERNS = "survivorship_concerns"
    COVERAGE_CONCENTRATION = "coverage_concentration"
    RESOLUTION_LIMITATIONS = "resolution_limitations"


@dataclass(frozen=True)
class LimitationRecord:
    category: LimitationCategory
    description: str
    evidence: str
    permanent: bool


FREE_DATASET_LIMITATIONS: tuple[LimitationRecord, ...] = (
    LimitationRecord(
        LimitationCategory.MISSING_UNDERLYINGS,
        "Of the project's 12 target underlyings (AAPL, NVDA, TSLA, SPY, QQQ, MSFT, AMD, AMZN, META, GOOGL, "
        "NFLX, IWM), only AAPL and SPY have ANY real historical options data in this dataset; NVDA, TSLA, QQQ, "
        "MSFT, AMD, AMZN, META, GOOGL, NFLX are completely absent. The dataset's 4 other real underlyings "
        "(FOXA, GOOG, NWSA, TWX) are not on the target list at all.",
        evidence="phase27_coverage_report.TARGET_UNDERLYINGS / BONUS_NON_TARGET_UNDERLYINGS; phase27_dataset_manifest.build_manifest_entry.known_limitations",
        permanent=True,
    ),
    LimitationRecord(
        LimitationCategory.MISSING_YEARS,
        "Essentially no coverage of the project's 2019-2026 research window: AAPL's real data entirely predates "
        "it (2013-2016), and SPY has exactly one real day inside it (2023-08-03).",
        evidence="phase27_certified_expanded_dataset.EXPANDED_FINAL_GATE's coverage_is_general_purpose=False rationale",
        permanent=True,
    ),
    LimitationRecord(
        LimitationCategory.NO_NATIVE_IV,
        "Zero native/vendor-supplied implied volatility field exists anywhere in this dataset, for any underlying. "
        "Any IV value used in research is a Black-Scholes RECONSTRUCTED_IV (Part 2's research_features.py), never "
        "an observed market IV, and depends on an explicit, external, unverified risk-free-rate/dividend-yield "
        "assumption.",
        evidence="phase26_iv_greeks_certification.py module docstring; research_features.py's RECONSTRUCTED_IV labeling",
        permanent=True,
    ),
    LimitationRecord(
        LimitationCategory.NO_NATIVE_GREEKS,
        "Zero native/vendor-supplied Greeks (delta/gamma/theta/vega/rho) anywhere in this dataset. Any Greeks used "
        "in research are DERIVED_FROM_MODEL (Black-Scholes), never OBSERVED_FROM_SOURCE.",
        evidence="research_position_view.py's Greeks reconstruction, always DERIVED_FROM_MODEL or UNAVAILABLE, never OBSERVED_FROM_SOURCE",
        permanent=True,
    ),
    LimitationRecord(
        LimitationCategory.VOLUME_LIMITATIONS,
        "Real trade volume exists for the underlyings this dataset does cover, but only real options trades that "
        "actually occurred in the sample window are present -- a contract with zero real trade rows is "
        "indistinguishable from 'no trading occurred' vs. 'this contract never even existed'; the contract-\n"
        "selection engine (Part 3) treats a missing volume observation as INSUFFICIENT_DATA, never a fabricated 0.",
        evidence="contract_selection.py's INSUFFICIENT_DATA vs INSUFFICIENT_VOLUME distinction",
        permanent=True,
    ),
    LimitationRecord(
        LimitationCategory.OPEN_INTEREST_LIMITATIONS,
        "Real open interest exists only where the source's own openinterest files exist for a contract/date; not "
        "every quoted/traded contract-day has a paired real OI observation.",
        evidence="phase26_quality_rules.check_negative_open_interest; research_dataset.py's open_interest field stays None when absent",
        permanent=True,
    ),
    LimitationRecord(
        LimitationCategory.QUOTE_LIMITATIONS,
        "A real, confirmed one-sided-market phenomenon exists in this dataset (a bid or ask present without its "
        "counterpart) -- never silently treated as a valid two-sided quote; and 5 real bid>ask crossed-quote flags "
        "were found (all deep-OTM AAPL contracts at the exact 2014 split-boundary dates), a genuine but rare "
        "microstructure artifact, not a systemic defect.",
        evidence="phase26_lean_sample_parser.py's one-sided-market handling; phase27_certified_expanded_dataset.py's HISTORICAL_BID_ASK dimension note",
        permanent=True,
    ),
    LimitationRecord(
        LimitationCategory.CORPORATE_ACTION_LIMITATIONS,
        "This dataset carries no adjustment-metadata/corporate-actions feed of its own. The real AAPL 7-for-1 "
        "split (2014-06-09) produces an unmapped legacy/successor contract-identity discontinuity that this "
        "codebase's detector flags (13 real flags) but cannot resolve -- root cause is SOURCE_LIMITATION + "
        "MISSING_ADJUSTMENT_METADATA, never an asserted merge.",
        evidence="phase27_corporate_actions.py's find_split_boundary_discontinuities; CorporateActionRootCause",
        permanent=True,
    ),
    LimitationRecord(
        LimitationCategory.CONTRACT_LIFECYCLE_LIMITATIONS,
        "No listing-date field exists in this source -- ContractLifecycle.first_listed_date is always None. "
        "first_observable_date/last_trade_date are only the real min/max of dates this codebase actually saw a "
        "row for, never an assumption about when a contract was actually first tradable.",
        evidence="phase26_dataset_builder.build_contract_lifecycle's module-level docstring note",
        permanent=True,
    ),
    LimitationRecord(
        LimitationCategory.SURVIVORSHIP_CONCERNS,
        "FOXA, NWSA, and TWX are legacy/inactive or since-merged/renamed tickers (real corporate history, not a "
        "codebase artifact) -- any cross-underlying research drawing on this dataset must account for the real "
        "possibility that its underlying universe is not survivorship-bias-free.",
        evidence="phase27_dataset_manifest.build_manifest_entry.known_limitations",
        permanent=True,
    ),
    LimitationRecord(
        LimitationCategory.COVERAGE_CONCENTRATION,
        "7,358 real contracts concentrate overwhelmingly in AAPL (2013-2016); the remaining 5 underlyings "
        "contribute comparatively little and mostly cluster around a handful of real dates (e.g. GOOG's 3 "
        "consecutive real days in Dec 2015, SPY's single real day in Aug 2023) rather than a broad, even panel.",
        evidence="phase27_certified_expanded_dataset.py's dataset_label and real contract counts",
        permanent=True,
    ),
    LimitationRecord(
        LimitationCategory.RESOLUTION_LIMITATIONS,
        "Resolution is inconsistent across the dataset -- daily bars for most of the sample, real intraday "
        "minute-resolution data only for specific single/multi-day windows (e.g. SPY 2023-08-03, GOOG's 3-day "
        "Dec 2015 window) -- never uniformly minute-resolution across the full real date range.",
        evidence="phase27_dataset_manifest.build_manifest_entry's resolution field",
        permanent=True,
    ),
)


@dataclass(frozen=True)
class ResearchReportWithLimitations:
    report_body: str
    limitations: tuple[LimitationRecord, ...]


def render_limitations_markdown() -> str:
    lines = ["## Free Historical Options Dataset — Permanent Limitations", ""]
    for r in FREE_DATASET_LIMITATIONS:
        lines.append(f"- **{r.category.value}**: {r.description} (evidence: {r.evidence})")
    return "\n".join(lines)


def attach_limitations_disclosure(report_body: str) -> ResearchReportWithLimitations:
    """Every future research report should be constructed through this
    function (or otherwise include `FREE_DATASET_LIMITATIONS`) rather
    than citing the registry ad hoc -- see module docstring."""
    return ResearchReportWithLimitations(report_body=report_body, limitations=FREE_DATASET_LIMITATIONS)
