"""Phase 24, Part 17 — the historical-options-data-source scorecard.

Every row's `verification_level` says exactly how confident this
codebase should be in that row: `VERIFIED_REAL_PROBE` (a genuine
mcp__HOOD__* call made and inspected this phase or Phase 18 -- see
src.options.capability_audit / historical_depth_audit), or
`VENDOR_DOCUMENTATION_OR_THIRD_PARTY_SUMMARY` (gathered via web research
against vendor pages and/or third-party comparison articles, NOT
independently tested against a real API key this phase -- Part 5's own
instruction: 'Do not rely on marketing claims alone,' honored here by
labeling every unverified claim as exactly that, not by pretending web
research equals a real probe). No paid vendor was purchased or
API-tested this phase (Part 19/20).

Only Robinhood carries VERIFIED_REAL_PROBE rows. Every other vendor's
figures are the best available public information as of this phase's
research and may be stale, incomplete, or vendor-marketing-inflated --
treat them as a starting point for a future, deeper evaluation (Part 24's
recommendation), never as a purchasing decision made on this codebase's
authority.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class VerificationLevel(enum.Enum):
    VERIFIED_REAL_PROBE = "verified_real_probe"
    VENDOR_DOCUMENTATION_OR_THIRD_PARTY_SUMMARY = "vendor_documentation_or_third_party_summary"


class OverallClassification(enum.Enum):
    """Part 17's exact letter-grade vocabulary."""

    A = "a_strong_research_candidate"
    B = "b_usable_with_limitations"
    C = "c_partial"
    D = "d_inadequate"
    UNSUITABLE = "unsuitable"


@dataclass(frozen=True)
class VendorScorecardRow:
    source: str
    historical_depth: str
    daily_ohlc: str
    intraday: str
    bid_ask: str
    volume: str
    open_interest: str
    iv: str
    greeks: str
    expired_contracts: str
    historical_chain: str
    contract_lifecycle: str
    pit_capable: str
    api_access: str
    cost: str
    rate_limits: str
    licensing: str
    research_suitability: str
    overall_classification: OverallClassification
    verification_level: VerificationLevel
    notes: str


VENDOR_SCORECARD: tuple[VendorScorecardRow, ...] = (
    VendorScorecardRow(
        source="Robinhood (current HOOD MCP connector)",
        historical_depth="Daily OHLC + chain enumeration confirmed real back to ~2018 (SPY/AAPL probes, this phase); Phase 18 found real AAPL contracts to 2017-09-15.",
        daily_ohlc="YES -- confirmed real, no volume field.", intraday="Available (minute/5min/etc intervals exist per get_option_historicals' schema) but not probed this phase for options; equity intraday already used elsewhere in this project.",
        bid_ask="NO -- get_option_quotes (the only endpoint with bid/ask) is live-only, confirmed empty for an expired contract.",
        volume="NO -- 'Option bars carry no volume' (tool's own guide text).", open_interest="NO -- only in the live-only get_option_quotes.",
        iv="NO historically (present in live get_option_quotes only).", greeks="NO historically (present in live get_option_quotes only).",
        expired_contracts="YES -- state='expired' enumerates real expired contracts.", historical_chain="PARTIAL_CHAIN_CAPABILITY -- full strike ladder enumerable per expiration via state='expired', but no as-of-timestamp chain snapshot capability exists.",
        contract_lifecycle="HISTORICAL_CONTRACT_EXISTENCE_UNKNOWN -- no first-listed-date field anywhere in the schema; expiration reaching 'expired' state is confirmable, PIT listing is not.",
        pit_capable="NO -- see contract_lifecycle.", api_access="Already connected (this project's MCP server) -- zero marginal cost, zero new integration work.",
        cost="Free (already available).", rate_limits="Not separately audited this phase; existing project usage has not hit a documented limit.", licensing="Governed by this project's existing Robinhood/HOOD terms -- not separately re-audited this phase.",
        research_suitability="MEDIUM for OHLC-only research (proven, already in use Phase 19-23); LOW for any bid/ask/OI/IV/Greeks-dependent research (impossible from this source).",
        overall_classification=OverallClassification.B,
        verification_level=VerificationLevel.VERIFIED_REAL_PROBE,
        notes="The chain-enumeration capability is REAL and UNDEREXPLOITED -- Phase 19/20 hand-selected 2-3 strikes per underlying per expiration; the full ladder (often 60-100+ strikes) is enumerable today at zero additional cost. This is the single most actionable, zero-cost next step (Part 24's recommendation).",
    ),
    VendorScorecardRow(
        source="Polygon.io / Massive (rebranded Oct 2025)",
        historical_depth="Vendor claims coverage since 2014 for options.", daily_ohlc="YES (claimed).", intraday="YES -- trades/quotes/candlesticks claimed for the full US options market.",
        bid_ask="YES (claimed) -- NBBO quotes.", volume="YES (claimed).", open_interest="YES (claimed) -- via chain snapshot endpoint.",
        iv="YES (claimed).", greeks="YES (claimed).", expired_contracts="Not independently confirmed this phase.", historical_chain="YES (claimed) -- complete option chain snapshot endpoint including greeks/OI.",
        contract_lifecycle="Not independently confirmed this phase.", pit_capable="Not independently confirmed this phase.",
        api_access="REST, WebSocket, and flat-file downloads.", cost="Tiered: Options plans reported from ~$29/mo (Starter) up to ~$399/mo (All-Access); options-specific tiers (Basic/Starter/Developer/Advanced/Business) billed separately from stocks/forex/crypto.",
        rate_limits="Tier-dependent; not itemized in the sources reviewed this phase.", licensing="Not itemized in the sources reviewed this phase -- typically per-seat/redistribution restrictions common to this vendor class.",
        research_suitability="Plausibly HIGH if claims hold -- would need direct verification against a real (even free-tier) API key before relying on it.",
        overall_classification=OverallClassification.B,
        verification_level=VerificationLevel.VENDOR_DOCUMENTATION_OR_THIRD_PARTY_SUMMARY,
        notes="Recently rebranded (Polygon.io -> Massive, Oct 2025) -- some cited web content may reference the old brand/URLs. A leading candidate for direct evaluation.",
    ),
    VendorScorecardRow(
        source="ThetaData",
        historical_depth="Third-party sources describe intraday chain history 'since 2018.'", daily_ohlc="YES (claimed).", intraday="YES (claimed) -- tick-level trade+quote with NBBO pairing.",
        bid_ask="YES (claimed) -- paired with every trade.", volume="YES (claimed).", open_interest="Not confirmed in sources reviewed this phase.",
        iv="YES (claimed) -- calculated via bisection method from mid/NBB/NBO.", greeks="YES (claimed) -- 1st/2nd/3rd-order, calculated per tick using the contemporaneous underlying tick.",
        expired_contracts="Implied by 'any strike, any minute since 2018' framing, not independently confirmed.", historical_chain="Implied (chain-shaped access described), not independently confirmed.",
        contract_lifecycle="Not confirmed in sources reviewed this phase.", pit_capable="Plausible given tick-level intraday claims, not independently confirmed.",
        api_access="REST + Excel plugin described.", cost="Standard plan reported at ~$25/mo (real-time); historical/Value/Pro tier pricing not fully itemized in sources reviewed.",
        rate_limits="Not itemized in sources reviewed this phase.", licensing="Not itemized in sources reviewed this phase.",
        research_suitability="Plausibly HIGH given Greeks are CALCULATED (not vendor-black-box) from real NBBO+underlying ticks -- exactly the kind of defensible reconstruction Part 10 asks about, IF independently verified.",
        overall_classification=OverallClassification.B,
        verification_level=VerificationLevel.VENDOR_DOCUMENTATION_OR_THIRD_PARTY_SUMMARY,
        notes="The stated Greeks-calculation methodology (bisection IV from real NBBO + contemporaneous underlying tick, SOFR-based rate) is the most transparent of the vendors reviewed -- worth prioritizing for a direct evaluation.",
    ),
    VendorScorecardRow(
        source="Cboe DataShop",
        historical_depth="General DataShop coverage from 2004; option-quote-interval products specifically from January 2012.", daily_ohlc="YES -- EOD summary product.", intraday="YES -- trade-by-trade (TBT) and 10-minute interval summaries.",
        bid_ask="YES -- option quote products (EOD and 3:45pm ET snapshots).", volume="YES.", open_interest="Volume-by-capacity products described; explicit OI not itemized in sources reviewed.",
        iv="YES -- optional 'Calcs' add-on (implied volatilities).", greeks="YES -- optional 'Calcs' add-on.", expired_contracts="Plausible given the exchange-of-record positioning, not independently confirmed.",
        historical_chain="Plausible, not independently confirmed.", contract_lifecycle="Not confirmed in sources reviewed this phase.", pit_capable="Plausible given trade-by-trade depth, not independently confirmed.",
        api_access="Bulk file download (DataShop), not itemized as a streaming API in sources reviewed.", cost="Not itemized -- 'contact for pricing'; academic institutions get 50% off with a $500 minimum charge.",
        rate_limits="N/A (bulk download model).", licensing="Exchange-data licensing terms apply -- typically the most restrictive/expensive class of this vendor list; not itemized in sources reviewed.",
        research_suitability="Plausibly HIGH (exchange-of-record data) but licensing/cost likely the highest barrier of the vendors reviewed.",
        overall_classification=OverallClassification.B,
        verification_level=VerificationLevel.VENDOR_DOCUMENTATION_OR_THIRD_PARTY_SUMMARY,
        notes="As the exchange itself, this is the most authoritative possible source -- but likely the least accessible for a ~$1,000-account personal research project without institutional/academic pricing.",
    ),
    VendorScorecardRow(
        source="Databento (OPRA)",
        historical_depth="Historical OPRA trades/CBBO/OHLCV/instrument-definitions extended back roughly 10 additional years from a March-2023 baseline (per vendor blog) -- approximately 2013+.", daily_ohlc="YES.", intraday="YES -- top-of-book (MBP-1), minute-level consolidated NBBO (CBBO-1m), and OHLCV aggregates at multiple intervals.",
        bid_ask="YES -- consolidated NBBO across all 17 national options exchanges.", volume="YES.", open_interest="Statistics schema described; explicit OI not itemized in sources reviewed.",
        iv="Not itemized as a raw field in sources reviewed (OPRA itself is a raw-tape feed; IV would likely need to be computed downstream).", greeks="Same caveat as IV.", expired_contracts="Plausible given raw-tape/instrument-definition schema, not independently confirmed.",
        historical_chain="Instrument-definition schema described as covering the full historical instrument universe -- plausible chain reconstruction, not independently confirmed.", contract_lifecycle="Plausible via instrument-definition schema, not independently confirmed.", pit_capable="Plausible (true raw-tape reconstruction), not independently confirmed.",
        api_access="Python/Rust/C++ clients, CSV/JSON/binary (DBN) encodings.", cost="Pay-as-you-go; a free credit is described for historical data. No flat monthly figure found in sources reviewed.",
        rate_limits="Not itemized in sources reviewed this phase.", licensing="Not itemized in sources reviewed this phase -- raw OPRA redistribution typically carries exchange-license obligations.",
        research_suitability="Plausibly HIGH for microstructure-grade, PIT-faithful research given the raw-tape design -- but IV/Greeks would need to be computed downstream, not supplied directly.",
        overall_classification=OverallClassification.B,
        verification_level=VerificationLevel.VENDOR_DOCUMENTATION_OR_THIRD_PARTY_SUMMARY,
        notes="The most 'raw and faithful' architecture of the vendors reviewed (true consolidated tape), at the cost of needing to compute IV/Greeks/OI reconstruction logic downstream rather than receiving them directly.",
    ),
    VendorScorecardRow(
        source="ORATS",
        historical_depth="Near-EOD data since 2007; 1-minute intraday since August 2020.", daily_ohlc="YES.", intraday="YES -- 1-minute since Aug 2020; any-minute chain reconstruction described.",
        bid_ask="YES -- 'high quality bid-ask quotes,' gathered ~14 minutes before close specifically to avoid wide closing spreads.", volume="Not itemized explicitly in sources reviewed (implied alongside OI/greeks).", open_interest="Implied as part of the standard data set, not itemized explicitly in sources reviewed.",
        iv="YES -- Smoothed Market Values (SMV) system, ATM term structure, interpolated IV at multiple deltas/tenors.", greeks="YES -- full SMV greeks.", expired_contracts="Plausible given 2007+ historical depth claims, not independently confirmed.",
        historical_chain="YES (claimed) -- 'go back in time to the options chain for any minute during the trading day.'", contract_lifecycle="Not itemized in sources reviewed this phase.", pit_capable="YES (claimed) -- the intraday-chain-reconstruction framing directly targets this.",
        api_access="REST Data API + Intraday Data API; also available via a Tradier brokerage partnership.", cost="Reported (orats.com itself was unreachable this phase): Delayed Data API $99/mo (20,000 req); Live Data API $199/mo (100,000 req); Live Intraday API $399/mo (1,000,000 req); a $29 14-day trial reported to exist.",
        rate_limits="Request-count-based, tier-dependent (see cost).", licensing="Not itemized in sources reviewed this phase.",
        research_suitability="Plausibly HIGH -- of the vendors reviewed, ORATS makes the most direct, specific PIT-chain-reconstruction and bid-ask-quality claims at the most accessible price point ($99-399/mo).",
        overall_classification=OverallClassification.A,
        verification_level=VerificationLevel.VENDOR_DOCUMENTATION_OR_THIRD_PARTY_SUMMARY,
        notes="The strongest candidate on paper for this project's exact need (PIT chain + IV/Greeks + bid-ask at an individual-researcher price point) -- the top recommendation for direct evaluation (Part 24).",
    ),
    VendorScorecardRow(
        source="OptionMetrics IvyDB (US)",
        historical_depth="Complete EOD record from January 1996 onward -- the deepest historical coverage of any vendor reviewed.", daily_ohlc="YES (underlying OHLC included).", intraday="Not the product's focus (EOD-oriented).",
        bid_ask="YES -- closing bid/ask quote.", volume="YES.", open_interest="YES.", iv="YES.", greeks="Standard IvyDB product includes IV; full Greeks availability not itemized in sources reviewed.",
        expired_contracts="YES -- an academic-standard, survivorship-bias-free historical database by design.", historical_chain="YES -- complete historical option chains are the product's core design.", contract_lifecycle="Plausible given survivorship-free design, not itemized explicitly in sources reviewed.",
        pit_capable="YES (claimed) -- this is the closest to an academic gold-standard PIT options database of the vendors reviewed.",
        api_access="Primarily distributed via WRDS (Wharton Research Data Services) institutional subscriptions; a direct-to-OptionMetrics commercial path also exists.", cost="Not published; institutional/enterprise pricing, typically far above an individual-researcher budget. WRDS institutional access (if this project's operator has an affiliated university account) could make this free at the margin.",
        rate_limits="N/A (bulk database access model).", licensing="Academic/institutional licensing common via WRDS; commercial licensing terms not itemized in sources reviewed.",
        research_suitability="HIGH in principle (300+ institutions use it for peer-reviewed research) -- but almost certainly cost/licensing-inaccessible for a ~$1,000-account personal project without an existing WRDS affiliation.",
        overall_classification=OverallClassification.C,
        verification_level=VerificationLevel.VENDOR_DOCUMENTATION_OR_THIRD_PARTY_SUMMARY,
        notes="Worth exactly one question: does the project's operator already have WRDS access through a university affiliation? If yes, this becomes the strongest possible candidate at zero marginal cost. If no, treat as inaccessible.",
    ),
    VendorScorecardRow(
        source="Tradier (brokerage API, options data via ORATS partnership)",
        historical_depth="Not itemized in sources reviewed this phase.", daily_ohlc="YES via history endpoint.", intraday="Not itemized in sources reviewed this phase.",
        bid_ask="NOT available on Tradier's own native API; bid-ask/Greeks/IV are supplied through Tradier's ORATS partnership, not Tradier itself.", volume="YES (last-price/volume via native API).", open_interest="Via ORATS partnership.",
        iv="Via ORATS partnership.", greeks="Via ORATS partnership.", expired_contracts="Not itemized in sources reviewed this phase.", historical_chain="Options chain endpoint exists; historical-as-of capability not itemized.",
        contract_lifecycle="Not itemized in sources reviewed this phase.", pit_capable="Not itemized in sources reviewed this phase.",
        api_access="REST brokerage API (this project already has a HOOD-equivalent broker relationship pattern; Tradier would be a genuinely separate integration).", cost="Brokerage-account-based; specific options-data-add-on pricing not itemized in sources reviewed.",
        rate_limits="Not itemized in sources reviewed this phase.", licensing="Not itemized in sources reviewed this phase.",
        research_suitability="LOW as a standalone historical-data source -- its real value (ORATS-sourced Greeks/bid-ask) is just ORATS again, one integration layer removed.",
        overall_classification=OverallClassification.D,
        verification_level=VerificationLevel.VENDOR_DOCUMENTATION_OR_THIRD_PARTY_SUMMARY,
        notes="Not a genuinely separate candidate from ORATS for this project's purposes -- evaluate ORATS directly instead.",
    ),
    VendorScorecardRow(
        source="EODHD",
        historical_depth="Vendor claims '30+ years' of coverage for its overall market-data catalog; NOT confirmed to apply specifically to its options product (Part 5's own warning against marketing claims applies directly here).", daily_ohlc="YES (claimed) for options.", intraday="Not itemized in sources reviewed this phase.",
        bid_ask="Not itemized explicitly in sources reviewed this phase.", volume="Not itemized explicitly in sources reviewed this phase.", open_interest="Not itemized explicitly in sources reviewed this phase.",
        iv="YES (claimed).", greeks="YES (claimed).", expired_contracts="Not itemized in sources reviewed this phase.", historical_chain="Not itemized in sources reviewed this phase.",
        contract_lifecycle="Not itemized in sources reviewed this phase.", pit_capable="Not itemized in sources reviewed this phase.",
        api_access="REST API; options data costs 10 API calls per request under the vendor's credit system.", cost="Options add-on reported starting around $99.99/mo (base platform plans from ~$19.99/mo).",
        rate_limits="Credit-based (10 credits/request for options).", licensing="Not itemized in sources reviewed this phase.",
        research_suitability="UNCERTAIN -- the '30+ years' headline figure most likely describes the vendor's equity/EOD catalog broadly, not its options product specifically; this exact ambiguity is why Part 5 says not to rely on marketing claims.",
        overall_classification=OverallClassification.C,
        verification_level=VerificationLevel.VENDOR_DOCUMENTATION_OR_THIRD_PARTY_SUMMARY,
        notes="The single biggest verification gap of any vendor reviewed -- its options-specific historical depth needs direct confirmation before any further consideration.",
    ),
    VendorScorecardRow(
        source="QuantConnect (options data via AlgoSeek, bundled with the QC research/backtest environment)",
        historical_depth="Equity options minute-resolution data from January 2010 (AlgoSeek); a daily IV/Greeks 'universe' dataset from January 2012; index options (SPX/VIX/NDX) minute data from January 2012.", daily_ohlc="YES.", intraday="YES -- minute resolution.",
        bid_ask="Implied by AlgoSeek's standard options product design, not itemized explicitly in sources reviewed.", volume="YES (implied).", open_interest="Not itemized explicitly in sources reviewed.",
        iv="YES -- via the daily Options Universe dataset.", greeks="YES -- via the daily Options Universe dataset.", expired_contracts="Plausible given the 2010+ historical depth claim, not independently confirmed.",
        historical_chain="YES (claimed) -- the Options Universe dataset is explicitly chain-shaped (4,000 symbols).", contract_lifecycle="Not itemized in sources reviewed this phase.", pit_capable="Plausible given the dataset's design, not independently confirmed.",
        api_access="Primarily consumed WITHIN QuantConnect's own cloud research/backtesting environment (Lean engine / Research notebooks) -- not necessarily a portable raw-data export for use in this project's own pipeline.",
        cost="Data access is typically bundled with a QuantConnect subscription tier rather than sold as a standalone historical-data product; a specific standalone price for this data was not found in sources reviewed.",
        rate_limits="N/A within the QC environment; not itemized as a standalone API.", licensing="Data usage is scoped to the QuantConnect platform per its terms -- exporting raw data for use in an entirely separate pipeline (this project's own src/ codebase) is not confirmed to be permitted.",
        research_suitability="MEDIUM -- strong data, but the platform-lock-in question (can this project's own architecture actually USE the data outside QuantConnect's environment) needs a direct answer before this is a real candidate for this project specifically.",
        overall_classification=OverallClassification.C,
        verification_level=VerificationLevel.VENDOR_DOCUMENTATION_OR_THIRD_PARTY_SUMMARY,
        notes="Attractive if this project were willing to run its research INSIDE QuantConnect's environment; a mismatch if the goal is to keep expanding this repository's own src/options/ architecture, per Part 16's own framing.",
    ),
    VendorScorecardRow(
        source="Alpha Vantage",
        historical_depth="Not itemized as options-specific in sources reviewed.", daily_ohlc="Limited (sources describe options coverage as weak).", intraday="Not itemized in sources reviewed this phase.",
        bid_ask="Not itemized in sources reviewed this phase.", volume="Not itemized in sources reviewed this phase.", open_interest="Not itemized in sources reviewed this phase.",
        iv="Not itemized in sources reviewed this phase.", greeks="Not itemized in sources reviewed this phase.", expired_contracts="Not itemized in sources reviewed this phase.", historical_chain="Not itemized in sources reviewed this phase.",
        contract_lifecycle="Not itemized in sources reviewed this phase.", pit_capable="Not itemized in sources reviewed this phase.",
        api_access="REST API, request-per-minute tiered.", cost="Reported: $49.99/mo (75 req/min) up to $249.99/mo (1,200 req/min) -- but this pricing is for the platform generally, not options specifically.",
        rate_limits="Requests-per-minute tiered.", licensing="Not itemized in sources reviewed this phase.",
        research_suitability="LOW -- third-party sources consistently describe this vendor's options coverage as its weakest asset class.",
        overall_classification=OverallClassification.UNSUITABLE,
        verification_level=VerificationLevel.VENDOR_DOCUMENTATION_OR_THIRD_PARTY_SUMMARY,
        notes="Not a serious candidate for options-specific historical research based on available evidence.",
    ),
    VendorScorecardRow(
        source="Intrinio",
        historical_depth="Not itemized in sources reviewed this phase.", daily_ohlc="Not itemized in sources reviewed this phase.", intraday="Not itemized in sources reviewed this phase.",
        bid_ask="Not itemized in sources reviewed this phase.", volume="Not itemized in sources reviewed this phase.", open_interest="Not itemized in sources reviewed this phase.",
        iv="Not itemized in sources reviewed this phase.", greeks="Not itemized in sources reviewed this phase.", expired_contracts="Not itemized in sources reviewed this phase.", historical_chain="Not itemized in sources reviewed this phase.",
        contract_lifecycle="Not itemized in sources reviewed this phase.", pit_capable="Not itemized in sources reviewed this phase.",
        api_access="REST API (institutional-oriented).", cost="Described in sources reviewed only as 'expensive' / institutional-targeted -- no concrete figure found.",
        rate_limits="Not itemized in sources reviewed this phase.", licensing="Not itemized in sources reviewed this phase.",
        research_suitability="UNCERTAIN -- one third-party source described data quality as excellent but pricing as institutional; insufficient concrete evidence gathered this phase to grade further.",
        overall_classification=OverallClassification.C,
        verification_level=VerificationLevel.VENDOR_DOCUMENTATION_OR_THIRD_PARTY_SUMMARY,
        notes="Insufficient public information gathered this phase to grade with any confidence -- would need direct vendor contact for real figures.",
    ),
)


def rows_by_classification() -> dict[OverallClassification, list[str]]:
    out: dict[OverallClassification, list[str]] = {}
    for row in VENDOR_SCORECARD:
        out.setdefault(row.overall_classification, []).append(row.source)
    return out
