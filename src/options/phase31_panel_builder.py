"""Phase 31, foundational adapter — converts the real, certified free
dataset (Phase 26/27's `InMemoryLeanSampleStore`, exposed research-side
by Phase 30's `research_dataset.build_research_observations`/
`research_features.compute_features_for_contract`) into the FLAT
`list[dict]` "panel row" shape the project's existing options-alpha
research machinery expects (`src.research.ic`, `.quantile`,
`.cross_sectional_placebo`, `.multiple_testing`, `.overfitting_metrics`,
`src.options.mechanical_baseline`, `.dependence_bootstrap`,
`.placebo_extensions`).

NO SUCH ADAPTER EXISTED BEFORE THIS PHASE: Phase 19-23's options-alpha
campaigns built their panels from a DIFFERENT source (real, one-off
`mcp__HOOD__get_option_historicals` probe dumps, 2021-2023, 4-12
symbols) via one-off ingestion SCRIPTS
(`scripts/phase20_step1_ingest_expanded_panel.py`,
`scripts/phase22_step1_build_feature_panel.py`), never a reusable `src/`
function, and never touching the free QuantConnect/Lean dataset at all.
This module is that missing adapter for the free dataset specifically —
built once, here, because Phase 31 is the first campaign to need it.

CONVENTIONS DELIBERATELY MATCHED to the Phase 19-23 panel schema (so the
already-built, already-tested `src.research.*`/`src.options.
{mechanical_baseline,dependence_bootstrap,placebo_extensions}` machinery
works unmodified against these rows):
  - `moneyness_ratio`/`log_moneyness` use `src.options.moneyness`'s
    `underlying_price / strike` convention (Phase 19's, NOT Phase 30's
    `research_dataset.ResearchObservation.moneyness`, which is the
    inverse `strike / underlying_price` ratio — recomputed fresh here
    for consistency with the reused statistics literature rather than
    carried over inverted).
  - `underlying_symbol` AND `symbol` both carry the same value (some
    reused modules key one, some the other — see
    `docs/phase31_...md`'s reuse-audit note).
  - Forward targets are "N REAL OBSERVED BARS forward" (this contract's
    own next N real daily rows), NOT "N calendar days forward" — the
    same bar-based convention `src.research.targets.future_return` and
    the Phase 19-23 `forward_return_N` columns use, since the free
    dataset (like the legacy one) has real gaps (weekends, holidays,
    days a contract simply wasn't quoted).

COMPUTATIONAL-BUDGET SUBSAMPLE (disclosed, not hidden): the real free
dataset's DAILY-resolution AAPL/GOOG slice alone spans thousands of real
contracts; building every one into a full causal-feature + 5-horizon
target panel is not tractable in this environment's runtime budget.
`select_contracts()` takes a deterministic, evenly-strided (never
cherry-picked) sample of up to `max_contracts_per_underlying` REAL
contracts per underlying — a real, disclosed sampling choice over real
data, never a fabricated observation. See
`docs/phase31_options_alpha_round2.md` for the exact counts used.

DAILY-ONLY: only rows whose real `observation_timestamp` is midnight
(the Lean sample's daily-file convention — see
`phase26_quality_rules`/`phase27_coverage_report`'s existing
`has_daily_resolution` check) are used, since Part 4's horizons are
explicitly stated in DAYS. This means SPY (real coverage is a single
day of MINUTE bars only — Phase 26/27's real finding) contributes ZERO
rows to this panel; documented, not silently dropped.
"""

from __future__ import annotations

import bisect
import math
import statistics
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from src.options.expiration import bucket_dte, days_to_expiration
from src.options.moneyness import classify_moneyness
from src.options.moneyness import log_moneyness as compute_log_moneyness
from src.options.moneyness import moneyness_ratio as compute_moneyness_ratio
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.research_dataset import ResearchObservation, build_research_observations
from src.options.research_features import FeatureRow, compute_features_for_contract

HORIZONS: tuple[int, ...] = (1, 3, 5, 10, 20)
DEFAULT_MAX_CONTRACTS_PER_UNDERLYING = 250


def _is_daily(ts: datetime) -> bool:
    return ts.hour == 0 and ts.minute == 0 and ts.second == 0 and ts.microsecond == 0


def select_contracts(store: InMemoryLeanSampleStore, *, max_per_underlying: int = DEFAULT_MAX_CONTRACTS_PER_UNDERLYING) -> list[str]:
    """Deterministic, evenly-strided REAL-contract subsample per
    underlying — see module docstring's computational-budget note."""
    by_underlying: dict[str, list[str]] = defaultdict(list)
    for option_id, contract in store.contracts.items():
        by_underlying[contract.underlying_symbol].append(option_id)
    selected: list[str] = []
    for ids in by_underlying.values():
        ids = sorted(ids)
        if len(ids) <= max_per_underlying:
            selected.extend(ids)
            continue
        stride = len(ids) / max_per_underlying
        selected.extend(ids[int(i * stride)] for i in range(max_per_underlying))
    return sorted(selected)


def subset_store(store: InMemoryLeanSampleStore, contract_ids: list[str]) -> InMemoryLeanSampleStore:
    """A real, filtered VIEW of `store` restricted to `contract_ids` (and
    the underlyings those contracts belong to) — every real observation
    kept is byte-identical to the original store's; nothing is
    resampled, interpolated, or invented. Building this smaller store
    FIRST lets the campaign reuse Phase 30's `build_research_observations`
    (which otherwise scans the ENTIRE store, including contracts this
    subsample deliberately excludes) unmodified and at a tractable scale."""
    keep = set(contract_ids)
    contracts = {cid: c for cid, c in store.contracts.items() if cid in keep}
    lifecycles = {cid: l for cid, l in store.lifecycles.items() if cid in keep}
    quotes = {cid: v for cid, v in store.quotes.items() if cid in keep}
    trades = {cid: v for cid, v in store.trades.items() if cid in keep}
    open_interest = {cid: v for cid, v in store.open_interest.items() if cid in keep}
    underlyings_needed = {c.underlying_symbol for c in contracts.values()}
    underlying = {u: v for u, v in store.underlying.items() if u in underlyings_needed}
    return InMemoryLeanSampleStore(
        contracts=contracts, lifecycles=lifecycles, quotes=quotes, trades=trades,
        open_interest=open_interest, underlying=underlying,
    )


def build_underlying_series(store: InMemoryLeanSampleStore, underlying: str) -> list[tuple[date, float]]:
    """The real, date-sorted close series for `underlying` — the same
    (date -> real observed close) lookup discipline established in
    `phase27_coverage_report.build_field_availability_report`."""
    by_date: dict[date, float] = {}
    for o in store.underlying.get(underlying, []):
        if o.field == "close" and o.value is not None and o.timestamps.event_time is not None:
            by_date[o.timestamps.event_time.date()] = o.value
    return sorted(by_date.items())


def _underlying_index(series: list[tuple[date, float]], d: date) -> int | None:
    dates = [x[0] for x in series]
    idx = bisect.bisect_left(dates, d)
    if idx >= len(dates) or dates[idx] != d:
        return None
    return idx


def underlying_trailing_return(series: list[tuple[date, float]], d: date, *, lag: int = 1) -> float | None:
    idx = _underlying_index(series, d)
    if idx is None or idx < lag:
        return None
    prev = series[idx - lag][1]
    cur = series[idx][1]
    return (cur - prev) / prev if prev not in (None, 0) else None


def underlying_forward_returns_at(series: list[tuple[date, float]], d: date, horizons: tuple[int, ...]) -> dict[int, float | None]:
    idx = _underlying_index(series, d)
    out: dict[int, float | None] = {}
    for h in horizons:
        if idx is None:
            out[h] = None
            continue
        j = idx + h
        base = series[idx][1]
        out[h] = (series[j][1] - base) / base if j < len(series) and base not in (None, 0) else None
    return out


def _forward_option_targets(daily_rows: list[ResearchObservation], horizons: tuple[int, ...]) -> list[dict[str, float | None]]:
    closes = [r.option_close for r in daily_rows]
    highs = [r.option_high for r in daily_rows]
    lows = [r.option_low for r in daily_rows]
    n = len(daily_rows)
    out: list[dict[str, float | None]] = []
    for i in range(n):
        targets: dict[str, float | None] = {}
        base_close = closes[i]
        for h in horizons:
            j = i + h
            fwd_return = None
            abs_fwd = None
            if j < n and base_close not in (None, 0) and closes[j] is not None:
                fwd_return = (closes[j] - base_close) / base_close
                abs_fwd = abs(fwd_return)

            window_hi = min(i + h, n - 1)
            window_highs = [highs[k] for k in range(i + 1, window_hi + 1) if highs[k] is not None]
            window_lows = [lows[k] for k in range(i + 1, window_hi + 1) if lows[k] is not None]
            mfe = (max(window_highs) - base_close) / base_close if window_highs and base_close not in (None, 0) else None
            mae = (min(window_lows) - base_close) / base_close if window_lows and base_close not in (None, 0) else None

            window_closes = [closes[k] for k in range(i + 1, window_hi + 1) if closes[k] is not None]
            window_returns = [(b - a) / a for a, b in zip(window_closes, window_closes[1:]) if a not in (None, 0)]
            fwd_vol = statistics.stdev(window_returns) if len(window_returns) >= 2 else None

            targets[f"forward_option_return_{h}"] = fwd_return
            targets[f"abs_forward_option_return_{h}"] = abs_fwd
            targets[f"mfe_{h}"] = mfe
            targets[f"mae_{h}"] = mae
            targets[f"forward_realized_vol_{h}"] = fwd_vol
        out.append(targets)
    return out


def _base_row(
    obs: ResearchObservation, feat: FeatureRow, *, underlying_price_series: list[tuple[date, float]],
) -> dict[str, Any]:
    d = obs.observation_timestamp.date()
    underlying_price = obs.underlying_price
    log_m = None
    moneyness_r = None
    bucket = None
    if underlying_price is not None and underlying_price > 0 and obs.strike > 0:
        log_m = compute_log_moneyness(underlying_price, obs.strike)
        moneyness_r = compute_moneyness_ratio(underlying_price, obs.strike)
        bucket = classify_moneyness(underlying_price, obs.strike, obs.call_put).value
    moneyness_x_dte = log_m * obs.dte if (log_m is not None and obs.dte is not None) else None
    inverse_dte = 1.0 / (obs.dte + 1) if (obs.dte is not None and obs.dte >= 0) else None
    underlying_daily_return = underlying_trailing_return(underlying_price_series, d, lag=1)

    divergence = None
    if feat.option_return is not None and underlying_daily_return is not None:
        divergence = feat.option_return - underlying_daily_return
    convexity_proxy = underlying_daily_return ** 2 if underlying_daily_return is not None else None

    return {
        "timestamp": obs.observation_timestamp,
        "underlying_symbol": obs.underlying,
        "symbol": obs.underlying,
        "option_id": obs.option_id,
        "call_put": obs.call_put,
        "call_put_numeric": 1.0 if obs.call_put == "call" else 0.0,
        "strike": obs.strike,
        "expiration": obs.expiration,
        "dte": obs.dte,
        "dte_bucket": bucket_dte(obs.dte).value if obs.dte is not None else None,
        "inverse_dte": inverse_dte,
        "log_moneyness": log_m,
        "moneyness_ratio": moneyness_r,
        "moneyness_bucket": bucket,
        "moneyness_x_dte_interaction": moneyness_x_dte,
        "option_open": obs.option_open, "option_high": obs.option_high, "option_low": obs.option_low, "option_close": obs.option_close,
        "bid": obs.bid, "ask": obs.ask, "volume": obs.volume, "open_interest": obs.open_interest,
        "spread": feat.spread, "spread_pct": feat.spread_pct, "quote_availability": feat.quote_availability,
        "volume_oi_ratio": feat.volume_oi_ratio,
        "option_daily_return": feat.option_return, "option_momentum": feat.momentum, "option_mean_reversion": feat.mean_reversion,
        "option_range_expansion": feat.range_expansion_ratio, "option_recent_range_pct": feat.recent_range_pct,
        "option_rolling_vol": feat.rolling_vol,
        "underlying_price": underlying_price, "underlying_daily_return": underlying_daily_return,
        "underlying_momentum": feat.underlying_momentum, "underlying_realized_vol": feat.underlying_realized_vol,
        "vol_regime": feat.vol_regime, "trend": feat.trend, "drawdown": feat.drawdown,
        "reconstructed_iv": feat.reconstructed_iv, "iv_source": feat.iv_source,
        "option_underlying_divergence": divergence, "convexity_proxy": convexity_proxy,
        "data_quality": obs.data_quality.value, "pit_status": obs.pit_status.value,
        "cs_group_key": (obs.underlying, obs.expiration.isoformat(), obs.observation_timestamp),
    }


def _attach_peer_group_features(rows: list[dict]) -> None:
    """Second pass, IN PLACE: `relative_option_strength` (this row's own
    option_daily_return minus its economically-comparable peer group's
    mean — same underlying + expiration + real timestamp, per Part 5's
    "avoid comparing contracts that are not economically comparable")
    and `relative_price_rank` (percentile rank of option_close within
    that same peer group, in [0, 1]; 0.5 when the group has one member).
    Both use ONLY same-timestamp peer information — never a future
    observation."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["cs_group_key"]].append(row)
    for group_rows in groups.values():
        returns = [r["option_daily_return"] for r in group_rows if r["option_daily_return"] is not None]
        peer_mean_return = statistics.mean(returns) if returns else None
        closes = sorted((r["option_close"] for r in group_rows if r["option_close"] is not None))
        for row in group_rows:
            row["relative_option_strength"] = (
                row["option_daily_return"] - peer_mean_return
                if row["option_daily_return"] is not None and peer_mean_return is not None else None
            )
            if row["option_close"] is None or len(closes) < 2:
                row["relative_price_rank"] = 0.5 if row["option_close"] is not None else None
            else:
                rank = bisect.bisect_left(closes, row["option_close"])
                row["relative_price_rank"] = rank / (len(closes) - 1)


def build_panel_rows(
    store: InMemoryLeanSampleStore, *,
    max_contracts_per_underlying: int = DEFAULT_MAX_CONTRACTS_PER_UNDERLYING,
    horizons: tuple[int, ...] = HORIZONS, lookback: int = 5,
) -> list[dict]:
    """The real, complete panel-row builder. Returns rows sorted by
    (option_id, timestamp) — deterministic, reproducible given the same
    store and `max_contracts_per_underlying`."""
    contract_ids = select_contracts(store, max_per_underlying=max_contracts_per_underlying)
    small_store = subset_store(store, contract_ids)
    observations = build_research_observations(small_store)  # reuses Phase 30 unmodified

    by_contract: dict[str, list[ResearchObservation]] = defaultdict(list)
    for o in observations:
        if _is_daily(o.observation_timestamp):
            by_contract[o.option_id].append(o)

    underlying_series_cache: dict[str, list[tuple[date, float]]] = {}

    rows: list[dict] = []
    for option_id in sorted(by_contract):
        daily = sorted(by_contract[option_id], key=lambda r: r.observation_timestamp)
        if not daily:
            continue
        underlying = daily[0].underlying
        if underlying not in underlying_series_cache:
            underlying_series_cache[underlying] = build_underlying_series(small_store, underlying)
        u_series = underlying_series_cache[underlying]

        features = compute_features_for_contract(daily, lookback=lookback)
        forward_targets = _forward_option_targets(daily, horizons)

        for obs, feat, targets in zip(daily, features, forward_targets):
            row = _base_row(obs, feat, underlying_price_series=u_series)
            u_fwd = underlying_forward_returns_at(u_series, obs.observation_timestamp.date(), horizons)
            for h in horizons:
                row[f"forward_underlying_return_{h}"] = u_fwd[h]
                fwd_opt = targets[f"forward_option_return_{h}"]
                row[f"relative_to_underlying_{h}"] = (
                    fwd_opt - u_fwd[h] if fwd_opt is not None and u_fwd[h] is not None else None
                )
            row.update(targets)
            rows.append(row)

    _attach_peer_group_features(rows)
    rows.sort(key=lambda r: (r["option_id"], r["timestamp"]))
    return rows


def underlyings_with_daily_coverage(rows: list[dict]) -> tuple[str, ...]:
    return tuple(sorted({r["underlying_symbol"] for r in rows}))
