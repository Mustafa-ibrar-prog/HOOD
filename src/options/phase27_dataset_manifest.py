"""Phase 27, Part 11 — the canonical dataset manifest: a single record
per source that answers "what exact data did our research use?" without
ambiguity.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetManifestEntry:
    provider: str
    product: str
    dataset_version: str
    source_url_or_repository: str
    license: str
    retrieval_date: str  # ISO date
    date_range: str
    underlyings: tuple[str, ...]
    contract_count: int
    contract_day_count: int
    resolution: str
    fields: tuple[str, ...]
    pit_status: str
    execution_grade: str
    quality_score: str
    known_limitations: tuple[str, ...]
    sha256_fingerprint: str


def build_manifest_entry(
    *, contract_count: int, contract_day_count: int, underlyings: tuple[str, ...],
    date_range: str, sha256_fingerprint: str, retrieval_date: str,
) -> DatasetManifestEntry:
    """Every non-computed field below is a REAL fact established this
    phase (or Phase 26, unchanged) -- none is a template placeholder."""
    return DatasetManifestEntry(
        provider="QuantConnect/Lean (open-source repository, AlgoSeek-sourced bundled sample)",
        product="Data/option/usa/{daily,minute} sample options data + Data/equity/usa/daily paired underlying bars",
        dataset_version="phase27_quantconnect_lean_expanded_v1",
        source_url_or_repository="https://github.com/QuantConnect/Lean",
        license="Apache License 2.0 (repository LICENSE file, fetched and confirmed real in Phase 26 and unchanged this phase)",
        retrieval_date=retrieval_date,
        date_range=date_range,
        underlyings=underlyings,
        contract_count=contract_count,
        contract_day_count=contract_day_count,
        resolution="daily (AAPL/FOXA/GOOG/NWSA/TWX 2013-2016) + minute (AAPL/FOXA/GOOG/NWSA/TWX single/multi-day windows 2013-2015; SPY single day 2023-08-03)",
        fields=("contract_identity(strike/expiration/right/exercise_style)", "OHLC", "bid/ask+sizes", "trade_price/size/volume", "open_interest"),
        pit_status="real, tested, zero adversarial violations (Phase 15 EventTimestamps machinery, reused unchanged)",
        execution_grade="A for contracts with both real quotes and real trades present; varies per contract -- see phase26_execution_realism per-contract reports",
        quality_score="see phase27_certified_expanded_dataset.EXPANDED_DATASET_CERTIFICATION for the full 15-dimension real score",
        known_limitations=(
            "no NVDA, TSLA, QQQ, MSFT, AMD, AMZN, META, GOOGL, or NFLX anywhere in this source",
            "essentially no general 2021-2024 coverage (one real SPY day: 2023-08-03)",
            "zero native IV/Greeks fields (RECONSTRUCTABLE via Black-Scholes only when a paired real underlying price exists in-sample)",
            "no exchange field; multiplier is an unconfirmed market-convention assumption (100)",
            "AAPL's 2014-06-09 7-for-1 split leaves an unmapped legacy/successor contract-identity discontinuity (Part 8 finding)",
            "FOXA/NWSA/TWX are legacy/inactive or since-merged tickers, not part of this project's live target underlying list",
        ),
        sha256_fingerprint=sha256_fingerprint,
    )
