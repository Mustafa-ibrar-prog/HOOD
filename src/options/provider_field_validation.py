"""Phase 25, Part 2/4 — ORATS field-by-field validation matrix and the
PAID_PROOF_REQUIRED log.

Evidence-tier discipline (Part 3's explicit instruction: "Do not
silently downgrade third-party information into 'verified.'"):

`orats.com`, `docs.orats.com`, `docs.orats.io`, and
`orats-python.readthedocs.io` were all confirmed EGRESS_BLOCKED from
this environment this phase (direct WebFetch errors) -- ORATS's own
official documentation was NOT directly reachable. No ORATS account was
created and no ORATS API key was ever obtained (Part 2's explicit
prohibition: no purchase, no paid plan, no payment credentials). ORATS's
advertised free trial requires a credit card up front (WebSearch finding,
sourced from a description of https://info.orats.com/free-trial) --
per Part 2's own instruction this triggers PAID_PROOF_REQUIRED and
direct hands-on/sample testing stopped there.

What WAS obtained, and is the basis for every row below, is real
field-level SOURCE CODE from `FyZyX/orats-python`
(github.com/FyZyX/orats-python), a maintained, MIT-licensed open-source
Python client wrapping the actual ORATS Data API. Its
`src/orats/constructs/api/data.py` module defines typed request/response
classes whose field names are the ORATS API's own real response schema
(a client library cannot invent field names that don't exist in the API
it wraps and still function) -- fetched twice, independently, via two
separate WebFetch calls against the raw GitHub content, with identical
results both times. This is a genuinely stronger evidence tier than a
marketing page or a third-party comparison article (Phase 24's evidence
tier for ORATS), but it is NOT the same as `VERIFIED_AVAILABLE` in this
matrix's strict sense -- no live API call was made, no real response
payload with real values was ever obtained, and the library's version
against the live API was not confirmed current. Every row's
`evidence_tier` says which kind of evidence backs it; every row's
`classification` uses ONLY Part 4's 4 required values.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class FieldClassification(enum.Enum):
    """Part 4's exact, fixed 4-value vocabulary. No 5th value is added
    anywhere in this module -- the finer evidence-tier distinction lives
    in `EvidenceTier` instead, never by inventing a new classification."""

    VERIFIED_AVAILABLE = "verified_available"
    VERIFIED_UNAVAILABLE = "verified_unavailable"
    CLAIMED_AVAILABLE_UNVERIFIED = "claimed_available_unverified"
    UNKNOWN = "unknown"


class EvidenceTier(enum.Enum):
    """A finer-grained honesty label, orthogonal to `FieldClassification`.
    ORATS_OPEN_SOURCE_CLIENT_SCHEMA is stronger than
    VENDOR_MARKETING_OR_THIRD_PARTY_SUMMARY (Phase 24's tier for ORATS)
    but strictly weaker than OWN_LIVE_API_PROBE (never reached this
    phase -- see module docstring)."""

    OWN_LIVE_API_PROBE = "own_live_api_probe"
    OPEN_SOURCE_CLIENT_LIBRARY_SCHEMA = "open_source_client_library_schema"
    VENDOR_MARKETING_OR_THIRD_PARTY_SUMMARY = "vendor_marketing_or_third_party_summary"
    NO_EVIDENCE_GATHERED = "no_evidence_gathered"


@dataclass(frozen=True)
class FieldValidationRow:
    field_category: str
    classification: FieldClassification
    evidence_tier: EvidenceTier
    evidence_source: str
    notes: str


# Every row backed by the real field names extracted from
# raw.githubusercontent.com/FyZyX/orats-python/main/src/orats/constructs/api/data.py
# (classes: Ticker, Strike, Money, MoneyImplied, MoneyForecast, Summary, Core,
# DailyPrice, HistoricalVolatility, DividendHistory, EarningsHistory,
# StockSplitHistory, IvRank) and the endpoint/request evidence in
# endpoints.py / request.py (trade_date-scoped historical querying).
ORATS_FIELD_VALIDATION_MATRIX: tuple[FieldValidationRow, ...] = (
    FieldValidationRow(
        field_category="Contract/strike identity (ticker, strike, expiration_date, call/put)",
        classification=FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED,
        evidence_tier=EvidenceTier.OPEN_SOURCE_CLIENT_LIBRARY_SCHEMA,
        evidence_source="orats-python Strike class: ticker, strike, expiration_date, trade_date, days_to_expiration; call/put distinguished by field prefix (call_*/put_*), not a separate right field.",
        notes="A usable identity (ticker+strike+expiration+right) is present in the schema. No explicit multiplier, exercise_style, or contract_status field was observed anywhere in the fetched classes -- see the separate UNKNOWN rows below for those.",
    ),
    FieldValidationRow(
        field_category="first_listed_date / last_trading_date (point-in-time listing dates)",
        classification=FieldClassification.UNKNOWN,
        evidence_tier=EvidenceTier.NO_EVIDENCE_GATHERED,
        evidence_source="Not observed in Ticker, Strike, or any other fetched class.",
        notes="Ticker.min_date/max_date describe the DATA COVERAGE range for a ticker, not a per-contract first-listed/last-traded date. Do not conflate the two (Part 7's exact PIT distinction, carried over from Phase 24).",
    ),
    FieldValidationRow(
        field_category="exercise_style (American/European)",
        classification=FieldClassification.UNKNOWN,
        evidence_tier=EvidenceTier.NO_EVIDENCE_GATHERED,
        evidence_source="Not observed in any fetched class.",
        notes="Not itemized in the ORATS API's own response schema as inspected via this client library. US single-name/index equity options are conventionally American-style, but that is a market-convention assumption, not a confirmed ORATS field -- must not be silently assumed if this data source is ever adopted.",
    ),
    FieldValidationRow(
        field_category="multiplier / contract_status",
        classification=FieldClassification.UNKNOWN,
        evidence_tier=EvidenceTier.NO_EVIDENCE_GATHERED,
        evidence_source="Not observed in any fetched class.",
        notes="Neither field appears in Strike, Ticker, or the other data classes fetched this phase.",
    ),
    FieldValidationRow(
        field_category="Underlying OHLC (adjusted and unadjusted)",
        classification=FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED,
        evidence_tier=EvidenceTier.OPEN_SOURCE_CLIENT_LIBRARY_SCHEMA,
        evidence_source="orats-python DailyPrice class: open, high, low, close, unadjusted_open, unadjusted_high, unadjusted_low, unadjusted_close.",
        notes="Both adjusted and unadjusted OHLC fields are named explicitly and distinctly -- a materially more transparent design than most vendors reviewed in Phase 24, if the schema is accurate.",
    ),
    FieldValidationRow(
        field_category="Bid/ask (price and size, call and put)",
        classification=FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED,
        evidence_tier=EvidenceTier.OPEN_SOURCE_CLIENT_LIBRARY_SCHEMA,
        evidence_source="orats-python Strike class: call_bid_price, call_ask_price, call_bid_size, call_ask_size, put_bid_price, put_ask_price, put_bid_size, put_ask_size -- all scoped by trade_date.",
        notes="Whether these are NBBO-derived or vendor-reconstructed, and the exact intraday snapshot timing, is not documented in the evidence gathered this phase -- methodology itself remains UNKNOWN (see the separate methodology row).",
    ),
    FieldValidationRow(
        field_category="Volume",
        classification=FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED,
        evidence_tier=EvidenceTier.OPEN_SOURCE_CLIENT_LIBRARY_SCHEMA,
        evidence_source="orats-python Strike class: call_volume, put_volume. Also aggregated in Core: call_volume, put_volume, total_stock_volume, average_option_volume_20_day.",
        notes="Present at both the per-strike and per-underlying-aggregate level.",
    ),
    FieldValidationRow(
        field_category="Open interest",
        classification=FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED,
        evidence_tier=EvidenceTier.OPEN_SOURCE_CLIENT_LIBRARY_SCHEMA,
        evidence_source="orats-python Strike class: call_open_interest, put_open_interest. Also Core: call_open_interest, put_open_interest, open_interest.",
        notes="Present at both the per-strike and per-underlying-aggregate level, same as volume.",
    ),
    FieldValidationRow(
        field_category="Implied volatility (raw, and bid/mid/ask)",
        classification=FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED,
        evidence_tier=EvidenceTier.OPEN_SOURCE_CLIENT_LIBRARY_SCHEMA,
        evidence_source="orats-python Strike class: iv, external_iv, call_bid_iv, call_mid_iv, call_ask_iv, put_bid_iv, put_mid_iv, put_ask_iv.",
        notes="A raw IV plus a full bid/mid/ask IV spread per side -- more granular than a single closing-IV figure.",
    ),
    FieldValidationRow(
        field_category="Delta-bucketed implied volatility smile (0-100 delta)",
        classification=FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED,
        evidence_tier=EvidenceTier.OPEN_SOURCE_CLIENT_LIBRARY_SCHEMA,
        evidence_source="orats-python Money class: iv_0_delta through iv_100_delta in 5-delta increments (iv_5_delta, iv_10_delta, ... iv_95_delta, iv_100_delta) -- 21 fields.",
        notes="A full smile reconstruction at fixed deltas, per ticker/trade_date/expiration_date -- exactly the shape needed to study moneyness-dependent effects (relevant to this project's existing P22 moneyness-interaction hypotheses).",
    ),
    FieldValidationRow(
        field_category="IV rank / IV percentile",
        classification=FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED,
        evidence_tier=EvidenceTier.OPEN_SOURCE_CLIENT_LIBRARY_SCHEMA,
        evidence_source="orats-python IvRank class: iv, iv_rank_1_month, iv_percentile_1_month, iv_rank_1_year, iv_percentile_1_year.",
        notes="A dedicated endpoint/class for this, not a derived afterthought.",
    ),
    FieldValidationRow(
        field_category="Greeks (delta, gamma, theta, vega, rho, phi, driftless_theta)",
        classification=FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED,
        evidence_tier=EvidenceTier.OPEN_SOURCE_CLIENT_LIBRARY_SCHEMA,
        evidence_source="orats-python Strike class: delta, gamma, theta, vega, rho, phi, driftless_theta.",
        notes="One Greeks set per Strike row (not split call/put -- as with most vendors, Greeks are typically computed per specific contract, and this client's Strike row already represents a specific strike/expiration/trade_date). Calculation methodology (rate source, dividend treatment, American vs. European tree) is not documented in the evidence gathered this phase -- see the methodology row.",
    ),
    FieldValidationRow(
        field_category="IV/Greeks calculation methodology (rate source, dividend treatment, model)",
        classification=FieldClassification.UNKNOWN,
        evidence_tier=EvidenceTier.NO_EVIDENCE_GATHERED,
        evidence_source="Not documented anywhere in the client library's source or docstrings as fetched this phase; ORATS's own methodology pages were EGRESS_BLOCKED.",
        notes="The field NAMES are well-evidenced; the CALCULATION behind them is not. Do not assume a specific model (e.g. Black-Scholes vs. binomial) without direct confirmation.",
    ),
    FieldValidationRow(
        field_category="Historical volatility (multiple lookback windows)",
        classification=FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED,
        evidence_tier=EvidenceTier.OPEN_SOURCE_CLIENT_LIBRARY_SCHEMA,
        evidence_source="orats-python HistoricalVolatility class: hv_1_day through hv_1000_day (11 windows), plus close_to_close_hv_* and hv_ex_earnings_* variants -- 45+ fields total.",
        notes="Substantially more granular than any vendor in Phase 24's scorecard claimed.",
    ),
    FieldValidationRow(
        field_category="Dividends",
        classification=FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED,
        evidence_tier=EvidenceTier.OPEN_SOURCE_CLIENT_LIBRARY_SCHEMA,
        evidence_source="orats-python DividendHistory class: ticker, ex_dividend_date, dividend_amount, dividend_frequency, declared_date.",
        notes="A dedicated endpoint (/divs), not inferred from price-jump detection.",
    ),
    FieldValidationRow(
        field_category="Stock splits",
        classification=FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED,
        evidence_tier=EvidenceTier.OPEN_SOURCE_CLIENT_LIBRARY_SCHEMA,
        evidence_source="orats-python StockSplitHistory class: ticker, split_date, divisor.",
        notes="A dedicated endpoint (/splits) -- directly relevant to Part 15's corporate-action question.",
    ),
    FieldValidationRow(
        field_category="Earnings dates",
        classification=FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED,
        evidence_tier=EvidenceTier.OPEN_SOURCE_CLIENT_LIBRARY_SCHEMA,
        evidence_source="orats-python EarningsHistory class: ticker, earnings_date, time_of_day_announced. Also Core carries earnings_date_1..12 and per-event implied-move/straddle fields.",
        notes="A dedicated endpoint (/earnings) plus a rich forward-looking earnings-effect model in Core -- directly relevant to this project's existing earnings-related research (Phase 9/13).",
    ),
    FieldValidationRow(
        field_category="Historical date-scoped querying (point-in-time chain access)",
        classification=FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED,
        evidence_tier=EvidenceTier.OPEN_SOURCE_CLIENT_LIBRARY_SCHEMA,
        evidence_source="orats-python endpoints/data/request.py: DataHistoryApiRequest exposes a trade_date (aliased tradeDate) query parameter with validation requiring one of tickers or trade_date; endpoints.py shows a /hist/ URL-prefix convention (_is_historical=True) applying across /strikes, /monies/*, /summaries, /cores, /dailies, /hvs.",
        notes="This is a genuinely stronger PIT-query mechanism than Robinhood's (Phase 24 Part 7/18): it lets a caller ask 'what did the chain look like as of trade_date T' directly, rather than only 'did this contract eventually reach an expired state.' Still CLAIMED_AVAILABLE_UNVERIFIED, not VERIFIED_AVAILABLE -- no live query was actually issued this phase.",
    ),
    FieldValidationRow(
        field_category="Expired-contract queryability",
        classification=FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED,
        evidence_tier=EvidenceTier.OPEN_SOURCE_CLIENT_LIBRARY_SCHEMA,
        evidence_source="Inferred from the trade_date-scoped historical query design (a Strike row is keyed by trade_date+expiration_date+strike, not by a live/expired contract-state flag) plus Ticker.min_date/max_date implying multi-year coverage.",
        notes="No explicit contract-state field (analogous to Robinhood's state='expired') was observed -- this row is an inference from the query design, not a direct schema confirmation, so it stays CLAIMED_AVAILABLE_UNVERIFIED rather than being upgraded.",
    ),
    FieldValidationRow(
        field_category="Historical data depth (calendar coverage)",
        classification=FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED,
        evidence_tier=EvidenceTier.VENDOR_MARKETING_OR_THIRD_PARTY_SUMMARY,
        evidence_source="Carried over from Phase 24's web research: near-EOD data reported since 2007; 1-minute intraday reported since August 2020. NOT independently reconfirmed this phase (orats.com itself remained EGRESS_BLOCKED).",
        notes="This row's evidence tier is weaker than most others above -- the open-source client's schema proves WHAT fields exist, not HOW FAR BACK they actually populate. Depth remains an unverified vendor claim.",
    ),
    FieldValidationRow(
        field_category="Sample/live data validation against a real response payload",
        classification=FieldClassification.UNKNOWN,
        evidence_tier=EvidenceTier.NO_EVIDENCE_GATHERED,
        evidence_source="No account was created and no API key was obtained -- ORATS's free trial requires a credit card (Part 2's explicit PAID_PROOF_REQUIRED trigger).",
        notes="This is the single largest remaining gap: every CLAIMED_AVAILABLE_UNVERIFIED row above could, in principle, be wrong if the live API has drifted from the open-source client's schema (last verified update to that repository not confirmed) or if the client covers only a subset of a paid tier's real fields.",
    ),
    FieldValidationRow(
        field_category="Pricing terms",
        classification=FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED,
        evidence_tier=EvidenceTier.VENDOR_MARKETING_OR_THIRD_PARTY_SUMMARY,
        evidence_source="Carried over from Phase 24: reported (third-party) Delayed Data API ~$99/mo, Live Data API ~$199/mo, Live Intraday API ~$399/mo; a ~$29 14-day trial reported to exist elsewhere in third-party sources, in apparent tension with the credit-card-required free-trial page found this phase -- both reports are unverified and possibly describe different, non-overlapping offers.",
        notes="orats.com's own pricing page remained EGRESS_BLOCKED this phase -- see PAID_PROOF_REQUIRED_LOG below.",
    ),
    FieldValidationRow(
        field_category="Licensing / redistribution / automated-trading-use terms",
        classification=FieldClassification.UNKNOWN,
        evidence_tier=EvidenceTier.NO_EVIDENCE_GATHERED,
        evidence_source="Not found in any source reached this phase.",
        notes="Matters directly for this project, which is building an actual automated options-trading system (Part 18's own note) -- a future purchase decision must not proceed without confirming this first.",
    ),
)


@dataclass(frozen=True)
class PaidProofRequirement:
    provider: str
    requirement_note: str
    classification: str = "PAID_PROOF_REQUIRED"


PAID_PROOF_REQUIRED_LOG: tuple[PaidProofRequirement, ...] = (
    PaidProofRequirement(
        provider="ORATS",
        requirement_note="Free trial sign-up (https://info.orats.com/free-trial) reported to require a credit card before any sample data is issued (WebSearch finding this phase). Per Part 2's explicit instruction, direct hands-on/sample API testing stopped here -- no account created, no card entered.",
    ),
    PaidProofRequirement(
        provider="Databento",
        requirement_note="Its $125 free-credit pool is Stripe-gated -- payment information is collected up front even to draw down the free credits (WebSearch finding this phase). Treated as PAID_PROOF_REQUIRED under a literal reading of Part 2; not pursued further, no account created.",
    ),
)


def rows_by_classification() -> dict[FieldClassification, list[str]]:
    out: dict[FieldClassification, list[str]] = {}
    for row in ORATS_FIELD_VALIDATION_MATRIX:
        out.setdefault(row.classification, []).append(row.field_category)
    return out
