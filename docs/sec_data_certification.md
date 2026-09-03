# SEC Data Certification (Phase 17)

**SEC data certification does NOT imply predictive power.** This document
certifies that the SEC fundamental data pipeline is CORRECT, CAUSALLY
SAFE, and REPRODUCIBLE across AAPL, MSFT, NVDA, and JPM. No hypothesis
has been tested, no IC/Sharpe/PBO/DSR has been computed, and no claim is
made anywhere in this document or its underlying code about whether any
of this data predicts anything. See `docs/sec_data_source.md` for Phase
16's original capability documentation; this document extends it with
multi-issuer validation.

## Certification levels

| Concept | Level | AAPL | MSFT | NVDA | JPM |
|---|---|---|---|---|---|
| revenue | **CERTIFIED** | ✅ | ✅ | ✅ | ✅ |
| net_income | **CERTIFIED** | ✅ | ✅ | ✅ | ✅ |
| diluted_eps | **CERTIFIED** | ✅ | ✅ | ✅ | ✅ |
| total_assets | **CERTIFIED** | ✅ | ✅ | ✅ | ✅ |
| total_liabilities | **CERTIFIED** | ✅ | ✅ | ✅ | ✅ |
| stockholders_equity | **CERTIFIED** | ✅ | ✅ | ✅ | ✅ |
| operating_cash_flow | **CERTIFIED** | ✅ | ✅ | ✅ | ✅ |
| operating_income | **CONDITIONALLY_CERTIFIED** | ✅ | ✅ | ✅ | ❌ missing |
| cash_and_equivalents | **CONDITIONALLY_CERTIFIED** | ✅ | ✅ | ✅ | ❌ missing |
| capital_expenditures | **CONDITIONALLY_CERTIFIED** | ✅ | unverified | unverified | unverified |

No concept is `NOT_CERTIFIED` — everything probed this phase either fully
certifies or certifies with an explicit, documented restriction.

## The revenue-tag split (real, confirmed)

AAPL and MSFT tag revenue as `RevenueFromContractWithCustomerExcludingAssessedTax`.
NVDA and JPM tag revenue as plain `Revenues` instead. Confirmed disjoint:
neither NVDA's nor JPM's filing has a single row under the other tag, and
neither AAPL's nor MSFT's filing has a row under `Revenues`. Both source
concepts are independently verified reliable and map to the same
normalized `revenue` concept (`src/data/sec_concepts.py`).

## JPM's real, structural gaps

- **Zero `OperatingIncomeLoss` facts.** Banks do not report a traditional
  GAAP operating-income line the way non-financial issuers do (JPM's
  income statement is structured around net interest income + noninterest
  income − noninterest expense instead). Confirmed by a real probe
  requesting it alongside 9 other concepts that DID return rows for JPM
  in the same call — not a parsing failure.
- **Zero `CashAndCashEquivalentsAtCarryingValue` facts.** JPM instead
  reports a real, consolidated `CashAndDueFromBanks` figure. This is
  **deliberately not equated** to `cash_and_equivalents` — its scope
  relative to a non-bank's cash-and-equivalents figure was not
  independently verified as equivalent (Part 6: "no silent semantic
  equivalence"). It is recorded in `CONCEPT_MAP` with `reliable=False`
  so the real alternative is traceable, not silently dropped.
- **Zero 10-Q filings** (Phase 16 finding, reconfirmed). JPM's coverage
  matrix shows 3 10-Ks and 0 10-Qs for 2021-2023.

## Instant vs. duration semantics (Part 8)

Confirmed across every fact ingested in Phases 16-17: balance-sheet
concepts (`total_assets`, `total_liabilities`, `stockholders_equity`,
`cash_and_equivalents`) are always **instant** facts (`period_start` is
always `None`); income-statement/cash-flow concepts (`revenue`,
`operating_income`, `net_income`, `operating_cash_flow`,
`capital_expenditures`, `diluted_eps`) are always **duration** facts
(both `period_start` and `period_end` present). `sec_period_semantics.py`
validates every whitelisted fact against this expectation — 0 violations
found across all 4 issuers this phase.

A secondary, real finding: a 10-K's balance sheet typically carries only
2 years of comparatives while its income statement/cash-flow statements
carry 3 (confirmed: MSFT's FY2023 10-K has `Assets`/`Liabilities` for
2022/2023 only, but `NetIncomeLoss`/`Revenue` for 2021/2022/2023) — a
normal, expected 10-K structural convention, not a data gap.

## Annual vs. quarterly semantics (Part 9)

**Confirmed decisively:** AAPL's Q3 FY2023 10-Q reports the SAME concept
(revenue, net income, operating income), in the SAME filing, as BOTH a
standalone-quarter duration fact (period 2023-04-02..2023-07-01, 90 days)
AND a year-to-date duration fact (period 2022-09-25..2023-07-01, 279
days) — both `axises=()`, both real. **No derivation
(quarter = YTD − prior-YTD) is implemented anywhere in this codebase**,
and none is needed: the source already supplies standalone-quarter facts
directly. `src/data/sec_period_semantics.py`'s `DurationSpanClass`
(QUARTERLY ~80-100d, SEMIANNUAL_YTD ~170-190d, NINE_MONTH_YTD ~260-285d,
ANNUAL ~350-380d, OTHER) disambiguates which duration fact a caller wants
for a given `(concept, period_end)` pair, since more than one can share
the same `period_end`.

This was only probed via AAPL's 10-Q; MSFT/NVDA/JPM quarterly-vs-YTD
representation was not independently re-verified this phase (their 10-Q
filing *index* coverage was confirmed in Phase 16, but fact-level 10-Q
data was not fetched for them in Phase 17) — flagged as **UNVERIFIED**
for those three issuers, not assumed identical to AAPL's pattern.

## Amendments (Part 10)

Real probes (`get_sec_filing_index`, `form_type=["10-K/A","10-Q/A"]`,
`since=2018-01-01`, `until=2024-12-31`) for **all four issuers** — AAPL,
MSFT, NVDA, JPM — returned **zero amendments**. Amendment-supersession
behavior (a later `10-K/A` correctly superseding an earlier `10-K` in
`latest_known_value`, while both remain permanently stored) is therefore
verified only via **deterministic fixtures**
(`tests/test_sec_snapshot_and_dataset.py`,
`tests/test_sec_filing_store.py`) — real-world amendment coverage for
this universe/window remains **UNVERIFIED**, reported as such rather than
assumed safe.

## Point-in-time snapshot matrix (Part 11)

Verified across all 4 issuers, using each issuer's own real 10-K filing
date (never an invented publication time): the fact is unavailable at
`T_filing_date` 00:00:00, unavailable at `T_filing_date` 23:59:59
(same-day conservatism, Part 12), and available starting
`T_filing_date + 1 day`. Every issuer uses a genuinely distinct real
filing date (AAPL 2022-10-28, MSFT 2023-07-27, NVDA 2023-02-24, JPM
2023-02-21) — not one shared/hardcoded date across issuers.

## Missing-data policy (Part 14)

Every missing concept in this document is attributed to one of:
`SOURCE_DOES_NOT_REPORT_CONCEPT` (JPM operating_income),
`SOURCE_REPORTS_UNDER_DIFFERENT_TAXONOMY` (JPM cash_and_equivalents),
`SOURCE_RESPONSE_INCOMPLETE` (capex for MSFT/NVDA/JPM — genuinely never
probed, not confirmed absent). No missing value was ever converted to
zero, forward-filled, or backfilled from a later fact.

## Dataset certification (Part 17)

`certify_sec_fundamentals_asof_dataset` verifies, for any
`SEC_FUNDAMENTALS_ASOF` run: every observation has provenance, no
observation violates the publication policy, every referenced concept
has a certification entry, every referenced concept's unit is
documented, every issuer is in the declared universe, the dataset version
is fully populated, and `fingerprint()` is deterministic. Run against a
real 4-issuer, 12-month, 9-concept generation (432 observations): **PASSED**,
all 7 checks green.

## Survivorship bias (unchanged)

The universe remains `CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED`. SEC data
does not solve survivorship bias — no issuer was added to any universe
because SEC data exists for it, and no point-in-time constituent
reconstruction was attempted this phase.

## Reproducibility

Every certification claim in this document is backed by a script
(`scripts/phase17_step1_ingest_multi_issuer_facts.py`,
`scripts/phase17_step2_certification_report.py`) that reproduces it
deterministically from the ingested real data — re-running either script
reproduces the exact same coverage matrix, taxonomy audit, and
certification result.

## Remaining limitations

- Capital expenditures certified only for AAPL.
- 10-Q fact-level quarterly/YTD semantics confirmed only for AAPL.
- Real amendment behavior unverified for all 4 issuers (none exist in
  the probed window).
- JPM's 10-Q gap and missing operating_income/cash_and_equivalents
  concepts mean any future JPM-inclusive fundamental research must
  either exclude JPM for those concepts or treat it as a distinct case.
- This certification says nothing about whether any of this data is
  predictive of anything. That question is explicitly out of scope for
  this phase and remains open for a future phase to address.
