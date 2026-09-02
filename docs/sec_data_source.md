# SEC Filing Data Source (Phase 16)

Status as of Phase 16: **SEC filings are adopted as a research data
source. No alpha claim has been made about them** — Phase 15 identified
SEC filings as the most promising candidate data source (historically
backfillable, point-in-time-safe, free, low-complexity); Phase 16 built
the concrete integration and verified real coverage; no phase has yet
tested whether any SEC-derived feature predicts anything.

## What was verified, and how

Every claim below comes from a real, read-only `mcp__HOOD__get_sec_filing_index`
/ `mcp__HOOD__get_sec_filing_facts` call made during Phase 15/16
development — never inferred from tool names or documentation alone (see
`scripts/phase16_step1_ingest_sample_filings.py`'s module docstring for
the full evidence trail and exact `filing_id`s).

### Filing index (`get_sec_filing_index`)

Real fields returned, per filing: `filing_id`, `form_type`, `description`,
`date_filed`.

- **`filing_id` is a connector-internal UUID, not the standard SEC EDGAR
  accession-number format** (`nnnnnnnnnn-nn-nnnnnn`). It is stable and
  unique, so it serves the same join-key role, but must never be
  presented to a user as "the accession number."
- **`date_filed` is a DATE only — no time-of-day is ever supplied**, for
  any filing, of any form type, for any issuer probed. This drove the
  entire causal-timestamp design (see below).
- No amendment-status field: an amendment shows up as its own
  `form_type` string (`10-K/A`, `10-Q/A`), not a boolean flag on the
  original filing.

### Filing facts (`get_sec_filing_facts`)

Real fields returned, per fact: `filing_id`, `concept`, `entity` (the SEC
CIK, e.g. `0000320193` for AAPL), `period` (a single date for an instant
fact, or a `start/end` string for a duration fact — `start_date`/
`end_date` are also broken out separately), `value` (string-formatted),
`unit`, `decimals`, `char_value` (non-numeric facts), and `axises` (a
list of XBRL dimensional qualifiers).

- **No separate `taxonomy` field.** The us-gaap/dei/company-extension
  namespace is implicit in the bare tag name, never surfaced explicitly.
- **The same concept+period appears many times with different `axises`
  breakdowns** — only the row with `axises == []` is the consolidated,
  headline total. A naive ingestion that doesn't filter on this treats
  dozens of segment/product/fair-value-hierarchy sub-components as if
  they were duplicate observations of the same fact. `sec_fact_quality.py`
  classifies every dimensionally-qualified fact `METADATA_ONLY` for
  exactly this reason.
- **Not every company reports under identical tags.** Confirmed
  concretely: AAPL's FY2022 10-K does not use the concept `Revenues` at
  all (a real probe for it returned zero rows) — AAPL tags revenue as
  `RevenueFromContractWithCustomerExcludingAssessedTax` instead (axises
  `[]`, FY2022 value 394,328,000,000, matching Apple's real reported
  figure). `sec_concepts.py`'s `CONCEPT_MAP` lists only concepts
  independently confirmed this way; any concept not in that map is
  classified `REQUIRES_NORMALIZATION`, never silently coerced.

## Historical coverage (verified, not assumed)

| Issuer | 10-K | 10-Q | Notes |
|---|---|---|---|
| AAPL | 6 filings, 2020-10-30 → 2025-10-31 | 9 filings, 2021-01-28 → 2023-08-04 | Full coverage of and beyond the 2021-09-01..2023-08-31 discovery window |
| MSFT | 4 filings, 2020-07-31 → 2023-07-27 | 9 filings, 2021-01-26 → 2023-10-24 | Same |
| NVDA | 3 filings, 2021-02-26 → 2023-02-24 | 9 filings, 2021-05-26 → 2023-11-21 | Same |
| JPM | 3 filings, 2021-02-23 → 2023-02-21 | **0 filings** | **Verified gap, not a fetch failure** — JPM's 10-Q is not returned by this connector for 2021-2023 despite JPM being an active filer of 10-Ks in the same window. Any future research using this source must NOT assume uniform 10-Q coverage across issuers. |
| SPY | 0 filings | 0 filings | Confirms SEC issuer facts do not apply to this ETF (as Phase 15 expected). |

8-K coverage was also verified (23 filings for AAPL, 2021-01-05 →
2023-11-02) but 8-Ks are classified `METADATA_ONLY` — they are real,
event-driven disclosures, not standardized financial-statement facts, and
are not ingested into the fact store this phase.

## Causal timestamp policy

**`fiscal_period_end_date` is never used as a publication timestamp.**
Concretely demonstrated: AAPL's FY2022 fiscal year ended 2022-09-24, but
the 10-K reporting it wasn't filed until 2022-10-28 — over a month later.
A research timestamp of 2022-10-01 must not see that quarter's numbers;
one of 2022-10-29 may.

Since no source ever supplies a time-of-day, the only policy real data
this phase ingested supports is **`PUBLICATION_DATE_ONLY`**: a fact is
available only strictly *after* its filing's `date_filed` — the entire
filing date itself, including 23:59:59, is conservatively treated as
"not yet available" (Part 5's explicit instruction: prefer conservative
exclusion over guessing a time-of-day). An `EXACT_PUBLICATION_TIMESTAMP`
policy exists in the code for a future source that does supply a real
accepted-timestamp, but no real data probed this phase ever exercises it
— calling it without a real timestamp raises, rather than silently
falling back to a guess.

Amendments (`10-K/A`, `10-Q/A`) are separate filings with their own
`filing_id` and `date_filed` — never merged into or overwriting the
original. The snapshot engine's `latest_known_value` surfaces the most
recently *filed* version of a fact for a given fiscal period (so a later
amendment is reflected once it too becomes available), while the store
itself retains every version, permanently.

## Fact quality classification

Every ingested fact is classified into exactly one of:

- **SAFE_FOR_RESEARCH** — a consolidated (`axises == ()`) total for a
  concept with a verified, reliable normalized mapping.
- **REQUIRES_NORMALIZATION** — a consolidated total for a concept *not*
  in the verified whitelist (real data, unverified meaning).
- **METADATA_ONLY** — a dimensionally-qualified (segment/product/
  fair-value) breakdown, or a filing form (8-K) that carries no
  structured facts at all.
- **REJECTED** — a value violating a basic accounting invariant (e.g. a
  negative `Assets`/`Liabilities`/`StockholdersEquity`, which are
  non-negative by definition; `NetIncomeLoss`/`OperatingIncomeLoss` are
  explicitly exempt, since a loss is legitimate).

Duplicate detection, unit-consistency, and period-ordering checks all
run over the raw fact batch — a real duplicate (two identical
`NetIncomeLoss` rows in AAPL's own FY2022 10-K response) was found and
is preserved as a worked example in the ingestion script and its tests.

## Concept whitelist (Part 10)

Deliberately small — nine concepts, each independently confirmed against
a real reported figure: `revenue`, `operating_income`, `net_income`,
`diluted_eps`, `cash_and_equivalents`, `total_assets`,
`total_liabilities`, `stockholders_equity`, `operating_cash_flow`.
Capital expenditures was *not* probed this phase and is deliberately
absent rather than guessed.

## What this phase does NOT support

- **Point-in-time universe reconstruction.** The universe remains
  `CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED` — SEC data does not solve
  survivorship bias, and no issuer was added to any universe just
  because SEC data exists for it.
- **Uniform 10-Q coverage.** JPM is a confirmed, real counterexample.
- **Restatement/normalization beyond the nine-concept whitelist.** Every
  other concept is `REQUIRES_NORMALIZATION` by construction.
- **Any alpha claim.** No IC, Sharpe, PBO, DSR, or return-predictive
  test of any kind has been run on SEC data — that is explicitly out of
  scope for this phase and remains so until a future phase says
  otherwise.

## Reproducibility

Every dataset produced by `generate_sec_fundamentals_asof`
(`src/data/sec_dataset.py`) carries a `DatasetVersionRecord` whose
`fingerprint()` changes if the source, schema, universe, fact whitelist,
filing-form scope, or causal timestamp policy changes — two datasets
built under different assumptions can never collide on version identity.
