"""Phase 26, Part 8 — automated data-quality checks against the real,
ingested Lean sample. Every function is a pure detector: it returns
flags, it never repairs, rewrites, or drops a row. `QualityFlag`
instances are the only output -- nothing here mutates the store passed
in.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.options.historical_data_interfaces import ContractIdentity
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore


@dataclass(frozen=True)
class QualityFlag:
    rule: str
    contract_id: str
    detail: str
    severity: str  # "critical" | "warning"


def _obs_by_field(observations, field: str) -> list:
    return [o for o in observations if o.field == field]


def check_bid_gt_ask(store: InMemoryLeanSampleStore) -> list[QualityFlag]:
    flags = []
    for cid, obs in store.quotes.items():
        bids = {o.timestamps.event_time: o.value for o in _obs_by_field(obs, "bid")}
        asks = {o.timestamps.event_time: o.value for o in _obs_by_field(obs, "ask")}
        for ts, bid in bids.items():
            ask = asks.get(ts)
            if ask is not None and bid is not None and bid > ask:
                flags.append(QualityFlag("bid_gt_ask", cid, f"@{ts}: bid={bid} > ask={ask}", "critical"))
    return flags


def check_negative_or_zero_prices(store: InMemoryLeanSampleStore) -> list[QualityFlag]:
    flags = []
    for cid, obs in store.quotes.items():
        for o in obs:
            if o.field in ("bid", "ask", "bid_open", "bid_high", "bid_low", "ask_open", "ask_high", "ask_low") and o.value is not None and o.value < 0:
                flags.append(QualityFlag("negative_price", cid, f"{o.field}@{o.timestamps.event_time}={o.value}", "critical"))
    for cid, obs in store.trades.items():
        for o in obs:
            if o.field in ("price", "open", "high", "low") and o.value is not None and o.value < 0:
                flags.append(QualityFlag("negative_price", cid, f"{o.field}@{o.timestamps.event_time}={o.value}", "critical"))
    return flags


def check_negative_volume(store: InMemoryLeanSampleStore) -> list[QualityFlag]:
    flags = []
    for cid, obs in store.trades.items():
        for o in _obs_by_field(obs, "volume"):
            if o.value is not None and o.value < 0:
                flags.append(QualityFlag("negative_volume", cid, f"@{o.timestamps.event_time}={o.value}", "critical"))
    return flags


def check_negative_open_interest(store: InMemoryLeanSampleStore) -> list[QualityFlag]:
    flags = []
    for cid, obs in store.open_interest.items():
        for o in obs:
            if o.value is not None and o.value < 0:
                flags.append(QualityFlag("negative_open_interest", cid, f"@{o.timestamps.event_time}={o.value}", "critical"))
    return flags


def check_zero_or_invalid_strikes(store: InMemoryLeanSampleStore) -> list[QualityFlag]:
    flags = []
    for cid, c in store.contracts.items():
        if c.strike <= 0:
            flags.append(QualityFlag("invalid_strike", cid, f"strike={c.strike}", "critical"))
    return flags


def check_invalid_expirations(store: InMemoryLeanSampleStore) -> list[QualityFlag]:
    flags = []
    for cid, c in store.contracts.items():
        lc = store.lifecycles.get(cid)
        if lc is not None and lc.first_observable_date is not None and c.expiration < lc.first_observable_date:
            flags.append(QualityFlag("expiration_before_first_observation", cid,
                                      f"expiration={c.expiration} < first_observed={lc.first_observable_date}", "critical"))
    return flags


def check_option_type_mismatch(store: InMemoryLeanSampleStore) -> list[QualityFlag]:
    flags = []
    for cid, c in store.contracts.items():
        if c.call_put not in ("call", "put"):
            flags.append(QualityFlag("option_type_mismatch", cid, f"call_put={c.call_put!r}", "critical"))
        if cid != f"{c.underlying_symbol}_{c.call_put}_{c.strike:.4f}_{c.expiration.isoformat()}":
            flags.append(QualityFlag("contract_id_identity_mismatch", cid, "contract_id does not match its own identity fields", "critical"))
    return flags


def check_ohlc_violations(store: InMemoryLeanSampleStore) -> list[QualityFlag]:
    """High must be >= max(open, close) and low <= min(open, close),
    within each real trade bar."""
    flags = []
    for cid, obs in store.trades.items():
        by_ts: dict = {}
        for o in obs:
            by_ts.setdefault(o.timestamps.event_time, {})[o.field] = o.value
        for ts, fields in by_ts.items():
            if not {"open", "high", "low", "close"} <= fields.keys():
                continue
            o_, h_, l_, c_ = fields["open"], fields["high"], fields["low"], fields["close"]
            if h_ < max(o_, c_) or l_ > min(o_, c_) or h_ < l_:
                flags.append(QualityFlag("ohlc_violation", cid, f"@{ts}: open={o_} high={h_} low={l_} close={c_}", "critical"))
    return flags


def check_duplicate_observations(store: InMemoryLeanSampleStore) -> list[QualityFlag]:
    flags = []
    for cid, obs in store.quotes.items():
        seen = set()
        for o in obs:
            key = (o.field, o.timestamps.event_time)
            if key in seen:
                flags.append(QualityFlag("duplicate_row", cid, f"{o.field}@{o.timestamps.event_time} repeated", "warning"))
            seen.add(key)
    return flags


def check_missing_timestamps(store: InMemoryLeanSampleStore) -> list[QualityFlag]:
    flags = []
    for cid, obs in store.quotes.items():
        for o in obs:
            if o.timestamps.event_time is None:
                flags.append(QualityFlag("missing_timestamp", cid, f"field={o.field}", "critical"))
    return flags


def check_timestamp_ordering(store: InMemoryLeanSampleStore) -> list[QualityFlag]:
    """Within one contract's bid series, timestamps must be
    non-decreasing (rows appear in the file in real chronological
    order)."""
    flags = []
    for cid, obs in store.quotes.items():
        bid_ts = [o.timestamps.event_time for o in _obs_by_field(obs, "bid")]
        for prev, cur in zip(bid_ts, bid_ts[1:]):
            if cur < prev:
                flags.append(QualityFlag("timestamp_out_of_order", cid, f"{cur} follows {prev}", "critical"))
    return flags


def check_multiplier_not_source_confirmed(store: InMemoryLeanSampleStore) -> list[QualityFlag]:
    """Not a repair -- an explicit, permanent flag (Part 3): this
    source's multiplier is a market-convention assumption, never a
    source-confirmed field. See src.options.phase26_dataset_builder's
    module docstring."""
    from src.options.phase26_dataset_builder import MULTIPLIER_SOURCE_CONFIRMED
    if MULTIPLIER_SOURCE_CONFIRMED:
        return []
    return [QualityFlag("multiplier_not_source_confirmed", cid,
                         "multiplier=100 is a market-convention assumption, not stated by this data source", "warning")
            for cid in store.contracts]


ALL_QUALITY_RULES = (
    check_bid_gt_ask, check_negative_or_zero_prices, check_negative_volume, check_negative_open_interest,
    check_zero_or_invalid_strikes, check_invalid_expirations, check_option_type_mismatch, check_ohlc_violations,
    check_duplicate_observations, check_missing_timestamps, check_timestamp_ordering,
    check_multiplier_not_source_confirmed,
)


def run_all_quality_checks(store: InMemoryLeanSampleStore) -> list[QualityFlag]:
    flags: list[QualityFlag] = []
    for rule in ALL_QUALITY_RULES:
        flags.extend(rule(store))
    return flags
