"""Phase 30 shared SYNTHETIC_TEST_DATA fixtures.

Established Phase 27/29 discipline: synthetic fixtures exist ONLY to
exercise code mechanics (a merged row appears at the right timestamp, a
rejection code fires on a malformed input, ...) -- never imported by any
src/ module, never presented as real research evidence. Every function
here builds a small, deliberately-labeled `InMemoryLeanSampleStore`
in-memory; nothing touches the real on-disk dataset.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.data.source_profile import DataProvenance
from src.data.store_interfaces import ProvenancedObservation
from src.data.timestamp_model import EventTimestamps
from src.options.phase26_dataset_builder import (
    InMemoryLeanSampleStore,
    build_contract_identity,
    build_provenance,
)
from src.options.phase26_lean_sample_parser import LeanContractFileMeta

RETRIEVAL = datetime(2026, 9, 4, tzinfo=timezone.utc)


def _obs(key, field, value, ts):
    return ProvenancedObservation(
        key=key, field=field, value=value,
        timestamps=EventTimestamps(event_time=ts, observation_time=ts),
        provenance=DataProvenance.OBSERVED, source="phase30_synthetic_test_data",
    )


def synthetic_store(*, strike: float = 100.0, expiration: date = date(2026, 12, 18), underlying: str = "AAPL") -> InMemoryLeanSampleStore:
    """One clean call contract, two timestamps, quotes+trades+OI+underlying
    all present, no quality flags other than the permanent multiplier
    flag every contract in this dataset legitimately carries."""
    provenance = build_provenance(retrieval_timestamp=RETRIEVAL, adjustment_status="unadjusted_synthetic")
    meta = LeanContractFileMeta(underlying, "call", strike, expiration, "quote", "american", None)
    contract = build_contract_identity(meta, provenance)
    cid = contract.option_id

    ts0 = datetime(2026, 8, 1, 14, 30, tzinfo=timezone.utc)
    ts1 = datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)

    quotes = {cid: [
        _obs(cid, "bid", 4.80, ts0), _obs(cid, "ask", 5.00, ts0),
        _obs(cid, "bid", 4.90, ts1), _obs(cid, "ask", 5.10, ts1),
    ]}
    trades = {cid: [
        _obs(cid, "price", 4.90, ts0), _obs(cid, "open", 4.85, ts0),
        _obs(cid, "high", 4.95, ts0), _obs(cid, "low", 4.80, ts0), _obs(cid, "volume", 12.0, ts0),
    ]}
    oi = {cid: [_obs(cid, "open_interest", 340.0, ts0)]}
    underlying_obs = {underlying: [
        ProvenancedObservation(key=underlying, field="close", value=190.0,
                                timestamps=EventTimestamps(event_time=datetime(2026, 8, 1, tzinfo=timezone.utc)),
                                provenance=DataProvenance.OBSERVED, source="phase30_synthetic_test_data"),
    ]}
    from src.options.phase26_dataset_builder import build_contract_lifecycle
    lifecycle = build_contract_lifecycle(meta, [date(2026, 8, 1)], provenance, today=date(2026, 9, 4))

    return InMemoryLeanSampleStore(
        contracts={cid: contract}, lifecycles={cid: lifecycle},
        quotes=quotes, trades=trades, open_interest=oi, underlying=underlying_obs,
    )


def synthetic_multi_bar_store(
    *, n_bars: int = 8, strike: float = 100.0, expiration: date = date(2026, 12, 18), underlying: str = "AAPL",
) -> InMemoryLeanSampleStore:
    """A single call contract with `n_bars` real, sequential daily
    quote+trade+OI+underlying observations -- for exercising rolling
    window / momentum / no-lookahead feature-engine tests, which need
    more history than the 2-row `synthetic_store()` fixture provides."""
    provenance = build_provenance(retrieval_timestamp=RETRIEVAL, adjustment_status="unadjusted_synthetic")
    meta = LeanContractFileMeta(underlying, "call", strike, expiration, "quote", "american", None)
    contract = build_contract_identity(meta, provenance)
    cid = contract.option_id

    quotes_list, trades_list, oi_list, underlying_list = [], [], [], []
    dates = [date(2026, 8, 1 + i) for i in range(n_bars)]
    for i, d in enumerate(dates):
        ts = datetime(d.year, d.month, d.day, 15, 0, tzinfo=timezone.utc)
        option_close = 4.50 + 0.10 * i  # a steady, real, deterministic uptrend
        bid, ask = option_close - 0.10, option_close + 0.10
        underlying_price = 185.0 + 1.0 * i
        quotes_list += [_obs(cid, "bid", bid, ts), _obs(cid, "ask", ask, ts)]
        trades_list += [
            _obs(cid, "price", option_close, ts), _obs(cid, "open", option_close - 0.05, ts),
            _obs(cid, "high", option_close + 0.08, ts), _obs(cid, "low", option_close - 0.08, ts),
            _obs(cid, "volume", 10.0 + i, ts),
        ]
        oi_list.append(_obs(cid, "open_interest", 300.0 + 5 * i, ts))
        underlying_list.append(ProvenancedObservation(
            key=underlying, field="close", value=underlying_price,
            timestamps=EventTimestamps(event_time=datetime(d.year, d.month, d.day, tzinfo=timezone.utc)),
            provenance=DataProvenance.OBSERVED, source="phase30_synthetic_test_data",
        ))

    from src.options.phase26_dataset_builder import build_contract_lifecycle
    lifecycle = build_contract_lifecycle(meta, dates, provenance, today=date(2026, 9, 4))

    return InMemoryLeanSampleStore(
        contracts={cid: contract}, lifecycles={cid: lifecycle},
        quotes={cid: quotes_list}, trades={cid: trades_list}, open_interest={cid: oi_list},
        underlying={underlying: underlying_list},
    )


def synthetic_daily_multi_bar_store(
    *, n_bars: int = 8, strike: float = 100.0, expiration: date = date(2026, 12, 18), underlying: str = "AAPL",
) -> InMemoryLeanSampleStore:
    """Same shape as `synthetic_multi_bar_store`, but every quote/trade/OI
    timestamp is real midnight (Phase 26/27's actual DAILY-file
    convention -- see `phase26_quality_rules`/`phase27_coverage_report`'s
    `has_daily_resolution` check), for exercising Phase 31's
    daily-only-panel machinery, which filters on exactly that
    convention. `synthetic_multi_bar_store` intentionally keeps its
    original 15:00 timestamps (other already-passing tests depend on
    that exact fixture) -- this is a separate, additive fixture."""
    provenance = build_provenance(retrieval_timestamp=RETRIEVAL, adjustment_status="unadjusted_synthetic")
    meta = LeanContractFileMeta(underlying, "call", strike, expiration, "quote", "american", None)
    contract = build_contract_identity(meta, provenance)
    cid = contract.option_id

    quotes_list, trades_list, oi_list, underlying_list = [], [], [], []
    dates = [date(2026, 8, 1 + i) for i in range(n_bars)]
    for i, d in enumerate(dates):
        ts = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)  # midnight -- real daily-file convention
        option_close = 4.50 + 0.10 * i
        bid, ask = option_close - 0.10, option_close + 0.10
        underlying_price = 185.0 + 1.0 * i
        quotes_list += [_obs(cid, "bid", bid, ts), _obs(cid, "ask", ask, ts)]
        trades_list += [
            _obs(cid, "price", option_close, ts), _obs(cid, "open", option_close - 0.05, ts),
            _obs(cid, "high", option_close + 0.08, ts), _obs(cid, "low", option_close - 0.08, ts),
            _obs(cid, "volume", 10.0 + i, ts),
        ]
        oi_list.append(_obs(cid, "open_interest", 300.0 + 5 * i, ts))
        underlying_list.append(ProvenancedObservation(
            key=underlying, field="close", value=underlying_price,
            timestamps=EventTimestamps(event_time=ts),
            provenance=DataProvenance.OBSERVED, source="phase30_synthetic_test_data",
        ))

    from src.options.phase26_dataset_builder import build_contract_lifecycle
    lifecycle = build_contract_lifecycle(meta, dates, provenance, today=date(2026, 9, 4))

    return InMemoryLeanSampleStore(
        contracts={cid: contract}, lifecycles={cid: lifecycle},
        quotes={cid: quotes_list}, trades={cid: trades_list}, open_interest={cid: oi_list},
        underlying={underlying: underlying_list},
    )


def synthetic_store_with_crossed_market() -> InMemoryLeanSampleStore:
    """A deliberately malformed contract (bid > ask) to exercise
    FLAGGED_CRITICAL / DATA_QUALITY_FAILURE paths."""
    provenance = build_provenance(retrieval_timestamp=RETRIEVAL, adjustment_status="unadjusted_synthetic")
    meta = LeanContractFileMeta("AAPL", "put", 100.0, date(2026, 12, 18), "quote", "american", None)
    contract = build_contract_identity(meta, provenance)
    cid = contract.option_id
    ts0 = datetime(2026, 8, 1, 14, 30, tzinfo=timezone.utc)
    quotes = {cid: [_obs(cid, "bid", 6.0, ts0), _obs(cid, "ask", 5.0, ts0)]}
    return InMemoryLeanSampleStore(
        contracts={cid: contract}, lifecycles={}, quotes=quotes, trades={}, open_interest={}, underlying={},
    )
