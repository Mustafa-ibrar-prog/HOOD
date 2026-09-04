"""SYNTHETIC_TEST_DATA -- shared ORATS-shaped test fixtures for Phase 29.

Every row here uses REAL, verified ORATS field names (Phase 25's
open-source client schema evidence) but SYNTHETIC values -- except
where a value is explicitly noted as reused from a REAL, independently-
verified market fact (e.g. AAPL's real 2015-01-02 close), which is
called out explicitly. None of this is, or is ever presented as, an
actual ORATS API response (`RealDataVerificationRecord.
actually_returned_by_provider` must be False for anything built from
these rows). Never imported by any `src/` module -- only by tests.
"""

from __future__ import annotations

# A small, internally-consistent, multi-strike/multi-expiration AAPL
# chain slice -- SYNTHETIC price/IV/greeks values, but shaped exactly
# like a real ORATS /strikes response row (same key names).
SYNTHETIC_AAPL_STRIKES_20211201: list[dict] = [
    {
        "ticker": "AAPL", "tradeDate": "2021-12-01", "expirDate": "2022-01-21", "strike": 150.0,
        "callBidPrice": 5.20, "callAskPrice": 5.35, "callBidSize": 12, "callAskSize": 8,
        "callVolume": 340, "callOpenInterest": 5200,
        "putBidPrice": 2.10, "putAskPrice": 2.25, "putBidSize": 20, "putAskSize": 15,
        "putVolume": 120, "putOpenInterest": 3000,
        "iv": 0.28, "delta": 0.55, "gamma": 0.02, "theta": -0.05, "vega": 0.12, "rho": 0.03,
        "underlyingPrice": 165.30,
    },
    {
        "ticker": "AAPL", "tradeDate": "2021-12-01", "expirDate": "2022-01-21", "strike": 160.0,
        "callBidPrice": 2.10, "callAskPrice": 2.25, "callBidSize": 10, "callAskSize": 9,
        "callVolume": 200, "callOpenInterest": 3100,
        "putBidPrice": 4.80, "putAskPrice": 4.95, "putBidSize": 14, "putAskSize": 11,
        "putVolume": 90, "putOpenInterest": 2500,
        "iv": 0.27, "delta": 0.35, "gamma": 0.018, "theta": -0.04, "vega": 0.11, "rho": 0.02,
        "underlyingPrice": 165.30,
    },
    {
        "ticker": "AAPL", "tradeDate": "2021-12-01", "expirDate": "2022-02-18", "strike": 165.0,
        "callBidPrice": 6.50, "callAskPrice": 6.70, "callBidSize": 15, "callAskSize": 12,
        "callVolume": 410, "callOpenInterest": 6800,
        "putBidPrice": 6.20, "putAskPrice": 6.40, "putBidSize": 18, "putAskSize": 13,
        "putVolume": 380, "putOpenInterest": 5900,
        "iv": 0.29, "delta": 0.51, "gamma": 0.019, "theta": -0.055, "vega": 0.13, "rho": 0.025,
        "underlyingPrice": 165.30,
    },
]

# A second, later real calendar day for the SAME 150-strike Jan-2022
# expiration -- lets tests exercise multi-day PIT/chain-growth behavior,
# mirroring Phase 27's real GOOG multi-day test but with synthetic ORATS
# values.
SYNTHETIC_AAPL_STRIKES_20211202: list[dict] = [
    {
        "ticker": "AAPL", "tradeDate": "2021-12-02", "expirDate": "2022-01-21", "strike": 150.0,
        "callBidPrice": 5.35, "callAskPrice": 5.50, "callBidSize": 11, "callAskSize": 9,
        "callVolume": 300, "callOpenInterest": 5250,
        "putBidPrice": 2.00, "putAskPrice": 2.15, "putBidSize": 19, "putAskSize": 16,
        "putVolume": 110, "putOpenInterest": 3050,
        "iv": 0.275, "delta": 0.56, "gamma": 0.021, "theta": -0.051, "vega": 0.121, "rho": 0.031,
        "underlyingPrice": 166.10,
    },
]

# A real-value-reused row, for the IV/Greeks consistency cross-check
# (Part 6): AAPL's real 2015-01-02 close ($109.33) and the real
# AAPL_call_100_2016-01-15 mid quote ($17.65) this project already
# independently verified in Phase 26 -- reused here as the SYNTHETIC
# fixture's underlyingPrice/mid inputs so the consistency check is
# tested against numbers with a known-real BS-implied IV (~29.35%) to
# cross-validate against, not arbitrary made-up numbers.
SYNTHETIC_AAPL_REAL_VALUE_CROSSCHECK_ROW: dict = {
    "ticker": "AAPL", "tradeDate": "2015-01-02", "expirDate": "2016-01-15", "strike": 100.0,
    "callBidPrice": 17.55, "callAskPrice": 17.75, "callBidSize": 5, "callAskSize": 4,
    "callVolume": 50, "callOpenInterest": 800,
    "putBidPrice": 1.00, "putAskPrice": 1.10, "putBidSize": 8, "putAskSize": 7,
    "putVolume": 20, "putOpenInterest": 400,
    "iv": 0.295, "delta": 0.6687, "gamma": 0.0108, "theta": -0.0153, "vega": 0.3922, "rho": 0.5743,
    "underlyingPrice": 109.33,  # real AAPL close, Phase 26
}

# A row with a genuinely one-sided market (no real bid quoted) -- real
# phenomenon this project already found in Phase 26/27's actual data;
# reused here in schema-correct ORATS shape to prove the adapter handles
# a missing key the same honest way (never fabricates a 0.0).
SYNTHETIC_AAPL_ONE_SIDED_ROW: dict = {
    "ticker": "AAPL", "tradeDate": "2021-12-01", "expirDate": "2022-01-21", "strike": 300.0,
    # no callBidPrice/callBidSize key at all -- genuinely absent, not null
    "callAskPrice": 0.05, "callAskSize": 100,
    "callVolume": 5, "callOpenInterest": 900,
    "putBidPrice": 130.0, "putAskPrice": 135.0, "putBidSize": 2, "putAskSize": 2,
    "putVolume": 1, "putOpenInterest": 50,
    "iv": 0.90, "delta": 0.01, "gamma": 0.0001, "theta": -0.01, "vega": 0.02, "rho": 0.001,
    "underlyingPrice": 165.30,
}
