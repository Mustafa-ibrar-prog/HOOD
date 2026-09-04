"""Phase 32, Parts 3, 4 & 5/21 — causal bucket construction, bucketed
features, and forward bucket targets.

Built ENTIRELY on top of Phase 31's real, already-causal contract-day
panel (`phase31_panel_builder.build_panel_rows`'s output) — this module
never touches the raw store or re-ingests anything. Every bucket-day's
membership is exactly "which real contract-day rows Phase 31 already
built for that (underlying, call/put, DTE bucket, moneyness bucket,
date)" — since Phase 31's rows were themselves built with no forward-
looking survival requirement (a contract-day row exists iff a real
observation exists that day, independent of whether that contract
traded the day before or after), bucket membership inherits that same
NO-SURVIVORSHIP-LEAKAGE guarantee for free (Part 3's explicit warning:
"do not define today's bucket by asking which contracts eventually
survived until tomorrow" — nothing here ever looks forward to decide
who belongs in today's bucket).

ROW MODEL: one row per (underlying, call_put, dte_bucket, moneyness_bucket,
real date) — a "bucket-day." Forward targets are computed along each
bucket's own real date sequence (Part 5), exactly mirroring Phase 31's
bar-based horizon convention (N REAL bucket-dates forward, not N
calendar days).

"Future bucket return" (Part 5) has no single well-defined meaning at
the bucket level the way a single contract's close-to-close return does
(a bucket aggregates many different strikes; there is no one "bucket
price" to difference two dates of). This module defines it as the
COMPOUNDED PRODUCT of the bucket's own contemporaneous median daily
returns over the next h real bucket-dates — the standard way to turn a
return SERIES into a multi-period return (the same math an index's
daily-return series uses to produce a multi-day index return), applied
here to `bucket_median_return` rather than to a price level. Every
target that needs "the future" walks this same real per-bucket-date
return sequence — never a price level that does not exist for an
aggregate.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence

from src.options.phase32_bucket_definitions import BucketScheme

EXTREME_RETURN_THRESHOLD = 0.20  # a contemporaneous |return| beyond this counts as "extreme" -- fixed before any result was seen
_MONEYNESS_RANK_FINE = {"deep_itm": -2, "itm": -1, "near_atm": 0, "otm": 1, "deep_otm": 2}
_MONEYNESS_RANK_COARSE = {"itm_side": -1, "near_atm": 0, "otm_side": 1}
_DTE_RANK_FINE = {"0-7": 0, "8-30": 1, "31-60": 2, "61-120": 3, "120+": 4}
_DTE_RANK_COARSE = {"short": 0, "medium": 1, "long": 2}

BucketKey = tuple[str, str, str, str, date]  # (underlying, call_put, dte_bucket, moneyness_bucket, date)


@dataclass(frozen=True)
class BucketDayStats:
    underlying: str
    call_put: str
    dte_bucket: str
    moneyness_bucket: str
    date: date
    n_contracts: int
    n_valid_returns: int
    median_return: float | None
    mean_return: float | None
    return_dispersion: float | None
    positive_return_fraction: float | None
    extreme_return_fraction: float | None
    cross_sectional_range: float | None
    median_dte: float | None
    median_moneyness_ratio: float | None
    median_high_low_range: float | None
    median_bid: float | None
    median_ask: float | None
    median_volume: float | None
    median_open_interest: float | None
    median_spread_pct: float | None
    underlying_price: float | None
    underlying_daily_return: float | None
    underlying_realized_vol: float | None
    forward_underlying_returns: dict[int, float | None]


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def compute_bucket_day_stats(key: BucketKey, rows: Sequence[dict], *, horizons: Sequence[int] = ()) -> BucketDayStats:
    underlying, call_put, dte_bucket, moneyness_bucket, d = key
    returns = [r["option_daily_return"] for r in rows if r.get("option_daily_return") is not None]
    dte_values = [r["dte"] for r in rows if r.get("dte") is not None]
    moneyness_values = [r["moneyness_ratio"] for r in rows if r.get("moneyness_ratio") is not None]
    hl_ranges = [
        (r["option_high"] - r["option_low"]) / r["option_close"]
        for r in rows if r.get("option_high") is not None and r.get("option_low") is not None and r.get("option_close")
    ]
    bids = [r["bid"] for r in rows if r.get("bid") is not None]
    asks = [r["ask"] for r in rows if r.get("ask") is not None]
    volumes = [r["volume"] for r in rows if r.get("volume") is not None]
    ois = [r["open_interest"] for r in rows if r.get("open_interest") is not None]
    spreads = [r["spread_pct"] for r in rows if r.get("spread_pct") is not None]

    dispersion = statistics.stdev(returns) if len(returns) >= 2 else None
    positive_frac = (sum(1 for x in returns if x > 0) / len(returns)) if returns else None
    extreme_frac = (sum(1 for x in returns if abs(x) >= EXTREME_RETURN_THRESHOLD) / len(returns)) if returns else None
    cs_range = (max(returns) - min(returns)) if returns else None

    underlying_price = next((r["underlying_price"] for r in rows if r.get("underlying_price") is not None), None)
    underlying_daily_return = next((r["underlying_daily_return"] for r in rows if r.get("underlying_daily_return") is not None), None)
    underlying_realized_vol = next((r["underlying_realized_vol"] for r in rows if r.get("underlying_realized_vol") is not None), None)
    forward_underlying_returns = {
        h: next((r.get(f"forward_underlying_return_{h}") for r in rows if r.get(f"forward_underlying_return_{h}") is not None), None)
        for h in horizons
    }

    return BucketDayStats(
        underlying=underlying, call_put=call_put, dte_bucket=dte_bucket, moneyness_bucket=moneyness_bucket, date=d,
        n_contracts=len(rows), n_valid_returns=len(returns), median_return=_median(returns), mean_return=(statistics.mean(returns) if returns else None),
        return_dispersion=dispersion, positive_return_fraction=positive_frac, extreme_return_fraction=extreme_frac,
        cross_sectional_range=cs_range, median_dte=_median(dte_values), median_moneyness_ratio=_median(moneyness_values),
        median_high_low_range=_median(hl_ranges), median_bid=_median(bids), median_ask=_median(asks),
        median_volume=_median(volumes), median_open_interest=_median(ois), median_spread_pct=_median(spreads),
        underlying_price=underlying_price, underlying_daily_return=underlying_daily_return, underlying_realized_vol=underlying_realized_vol,
        forward_underlying_returns=forward_underlying_returns,
    )


def build_bucket_day_table(panel_rows: Sequence[dict], scheme: BucketScheme, *, horizons: Sequence[int] = ()) -> dict[BucketKey, BucketDayStats]:
    """The core causal aggregation step (Part 3): every real contract-day
    row is classified using ONLY information already on that row (its
    OWN dte_bucket/moneyness_bucket, themselves computed causally by
    Phase 31 from that day's own strike/underlying price), grouped, and
    reduced to one `BucketDayStats` per bucket-day. No row is ever
    assigned based on what happens after `date`."""
    grouped: dict[BucketKey, list[dict]] = defaultdict(list)
    for r in panel_rows:
        dte_b = scheme.coarsen_dte(r.get("dte_bucket"))
        money_b = scheme.coarsen_moneyness(r.get("moneyness_bucket"))
        if dte_b is None or money_b is None:
            continue
        key: BucketKey = (r["underlying_symbol"], r["call_put"], dte_b, money_b, r["timestamp"].date())
        grouped[key].append(r)
    return {key: compute_bucket_day_stats(key, rows, horizons=horizons) for key, rows in grouped.items()}


def _rank_maps(scheme: BucketScheme) -> tuple[dict[str, int], dict[str, int]]:
    if scheme.name == "fine":
        return _DTE_RANK_FINE, _MONEYNESS_RANK_FINE
    return _DTE_RANK_COARSE, _MONEYNESS_RANK_COARSE


def _linear_slope(xs: list[float], ys: list[float]) -> float | None:
    """A minimal, dependency-free simple-linear-regression slope --
    used only for `moneyness_slope`/`dte_slope`, which need more than 2
    points to be meaningful."""
    n = len(xs)
    if n < 3:
        return None
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom


def build_feature_rows(table: dict[BucketKey, BucketDayStats], scheme: BucketScheme) -> list[dict]:
    """Part 4's full feature set (A-E), attached to EVERY bucket-day row.
    B/C/D features compare a bucket-day's stats against SIBLING buckets
    sharing every dimension except one (call/put, moneyness, DTE
    respectively) on the SAME real date -- never a future date, never a
    different underlying."""
    dte_rank, moneyness_rank = _rank_maps(scheme)
    rows: list[dict] = []
    for key, stats in table.items():
        underlying, call_put, dte_bucket, moneyness_bucket, d = key

        # --- B. call/put structure: same underlying/dte/moneyness/date, other call_put ---
        other_cp = "put" if call_put == "call" else "call"
        sibling_cp = table.get((underlying, other_cp, dte_bucket, moneyness_bucket, d))
        call_put_return_spread = call_put_positive_fraction_spread = call_put_dispersion_diff = None
        if sibling_cp is not None:
            this_is_call = call_put == "call"
            call_stats, put_stats = (stats, sibling_cp) if this_is_call else (sibling_cp, stats)
            if call_stats.median_return is not None and put_stats.median_return is not None:
                call_put_return_spread = call_stats.median_return - put_stats.median_return
            if call_stats.positive_return_fraction is not None and put_stats.positive_return_fraction is not None:
                call_put_positive_fraction_spread = call_stats.positive_return_fraction - put_stats.positive_return_fraction
            if call_stats.return_dispersion is not None and put_stats.return_dispersion is not None:
                call_put_dispersion_diff = call_stats.return_dispersion - put_stats.return_dispersion

        # --- C. moneyness structure: same underlying/call_put/dte/date, sweep all moneyness buckets ---
        moneyness_siblings = {
            mb: table.get((underlying, call_put, dte_bucket, mb, d)) for mb in scheme.moneyness_values
        }
        atm_key = "near_atm"
        atm = moneyness_siblings.get(atm_key)
        atm_otm_spread = itm_atm_spread = otm_atm_spread = moneyness_slope = None
        if atm is not None and atm.median_return is not None:
            otm_keys = [mb for mb in scheme.moneyness_values if moneyness_rank.get(mb, 0) > 0]
            itm_keys = [mb for mb in scheme.moneyness_values if moneyness_rank.get(mb, 0) < 0]
            otm_returns = [moneyness_siblings[mb].median_return for mb in otm_keys if moneyness_siblings.get(mb) and moneyness_siblings[mb].median_return is not None]
            itm_returns = [moneyness_siblings[mb].median_return for mb in itm_keys if moneyness_siblings.get(mb) and moneyness_siblings[mb].median_return is not None]
            if otm_returns:
                otm_atm_spread = statistics.mean(otm_returns) - atm.median_return
                atm_otm_spread = -otm_atm_spread
            if itm_returns:
                itm_atm_spread = statistics.mean(itm_returns) - atm.median_return
        rank_xs, rank_ys = [], []
        for mb, sib in moneyness_siblings.items():
            if sib is not None and sib.median_return is not None:
                rank_xs.append(float(moneyness_rank.get(mb, 0)))
                rank_ys.append(sib.median_return)
        moneyness_slope = _linear_slope(rank_xs, rank_ys)

        # --- D. maturity structure: same underlying/call_put/moneyness/date, sweep all DTE buckets ---
        dte_siblings = {db: table.get((underlying, call_put, db, moneyness_bucket, d)) for db in scheme.dte_values}
        ordered_dte = sorted(scheme.dte_values, key=lambda db: dte_rank.get(db, 0))
        short_medium_spread = medium_long_spread = dte_slope = None
        if len(ordered_dte) >= 3:
            short_stats, medium_stats, long_stats = dte_siblings.get(ordered_dte[0]), dte_siblings.get(ordered_dte[len(ordered_dte) // 2]), dte_siblings.get(ordered_dte[-1])
            if short_stats and medium_stats and short_stats.median_return is not None and medium_stats.median_return is not None:
                short_medium_spread = medium_stats.median_return - short_stats.median_return
            if medium_stats and long_stats and medium_stats.median_return is not None and long_stats.median_return is not None:
                medium_long_spread = long_stats.median_return - medium_stats.median_return
        dte_xs, dte_ys = [], []
        for db, sib in dte_siblings.items():
            if sib is not None and sib.median_return is not None:
                dte_xs.append(float(dte_rank.get(db, 0)))
                dte_ys.append(sib.median_return)
        dte_slope = _linear_slope(dte_xs, dte_ys)

        # --- E. option-vs-underlying (contemporaneous; no delta -- not available in this dataset) ---
        option_minus_underlying_return = option_magnitude_minus_underlying_magnitude = dispersion_minus_underlying_vol = None
        if stats.median_return is not None and stats.underlying_daily_return is not None:
            option_minus_underlying_return = stats.median_return - stats.underlying_daily_return
            option_magnitude_minus_underlying_magnitude = abs(stats.median_return) - abs(stats.underlying_daily_return)
        if stats.return_dispersion is not None and stats.underlying_realized_vol is not None:
            dispersion_minus_underlying_vol = stats.return_dispersion - stats.underlying_realized_vol

        rows.append({
            "timestamp": datetime(d.year, d.month, d.day),
            "underlying_symbol": underlying, "symbol": underlying, "call_put": call_put,
            "call_put_numeric": 1.0 if call_put == "call" else 0.0,
            "dte_bucket": dte_bucket, "moneyness_bucket": moneyness_bucket,
            "option_id": f"{underlying}|{call_put}|{dte_bucket}|{moneyness_bucket}",  # the "bucket series" identity
            "expiration": dte_bucket,  # repurposed for phase31_robustness's stratification (documented)
            "n_contracts": stats.n_contracts, "n_valid_returns": stats.n_valid_returns,
            "bucket_median_return": stats.median_return, "bucket_mean_return": stats.mean_return,
            "bucket_return_dispersion": stats.return_dispersion, "bucket_positive_return_fraction": stats.positive_return_fraction,
            "bucket_extreme_return_fraction": stats.extreme_return_fraction, "bucket_cross_sectional_range": stats.cross_sectional_range,
            "bucket_median_dte": stats.median_dte, "bucket_median_moneyness_ratio": stats.median_moneyness_ratio,
            "bucket_median_high_low_range": stats.median_high_low_range,
            "bid": stats.median_bid, "ask": stats.median_ask, "volume": stats.median_volume, "open_interest": stats.median_open_interest,
            "spread_pct": stats.median_spread_pct,
            "call_put_return_spread": call_put_return_spread, "call_put_positive_fraction_spread": call_put_positive_fraction_spread,
            "call_put_dispersion_diff": call_put_dispersion_diff,
            "atm_otm_spread": atm_otm_spread, "itm_atm_spread": itm_atm_spread, "otm_atm_spread": otm_atm_spread, "moneyness_slope": moneyness_slope,
            "short_medium_dte_spread": short_medium_spread, "medium_long_dte_spread": medium_long_spread, "dte_slope": dte_slope,
            "option_minus_underlying_return": option_minus_underlying_return,
            "option_magnitude_minus_underlying_magnitude": option_magnitude_minus_underlying_magnitude,
            "dispersion_minus_underlying_vol": dispersion_minus_underlying_vol,
            "underlying_price": stats.underlying_price, "underlying_daily_return": stats.underlying_daily_return,
            "underlying_realized_vol": stats.underlying_realized_vol,
            "cs_group_key": (d,),  # cross-sectional peer group: every bucket that exists on this real date, across underlyings
            **{f"forward_underlying_return_{h}": v for h, v in stats.forward_underlying_returns.items()},
        })
    return rows


HORIZONS: tuple[int, ...] = (1, 3, 5, 10, 20)


def attach_forward_targets(rows: list[dict], horizons: tuple[int, ...] = HORIZONS) -> list[dict]:
    """Part 5: forward directional + non-directional targets, walked
    along each bucket-series' own real date sequence (grouped by
    `option_id`, i.e. the bucket identity excluding date)."""
    by_series: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_series[r["option_id"]].append(r)

    out: list[dict] = []
    for series_rows in by_series.values():
        series_rows.sort(key=lambda r: r["timestamp"])
        returns = [r["bucket_median_return"] for r in series_rows]
        dispersions = [r["bucket_return_dispersion"] for r in series_rows]
        underlying_returns_by_date: dict = {}  # filled lazily below via forward_underlying_return columns already on the row if present

        n = len(series_rows)
        for i, row in enumerate(series_rows):
            new_row = dict(row)
            for h in horizons:
                window = returns[i + 1:i + 1 + h]
                if len(window) == h and all(v is not None for v in window):
                    cum = 1.0
                    running_path = []
                    for v in window:
                        cum *= (1 + v)
                        running_path.append(cum - 1)
                    fwd_return = cum - 1
                    new_row[f"forward_bucket_return_{h}"] = fwd_return
                    new_row[f"forward_abs_bucket_return_{h}"] = abs(fwd_return)
                    new_row[f"forward_bucket_mfe_{h}"] = max(running_path)
                    new_row[f"forward_bucket_mae_{h}"] = min(running_path)
                else:
                    fwd_return = None
                    new_row[f"forward_bucket_return_{h}"] = None
                    new_row[f"forward_abs_bucket_return_{h}"] = None
                    new_row[f"forward_bucket_mfe_{h}"] = None
                    new_row[f"forward_bucket_mae_{h}"] = None

                disp_window = dispersions[i + 1:i + 1 + h]
                valid_disp = [v for v in disp_window if v is not None]
                fwd_disp = statistics.mean(valid_disp) if len(valid_disp) == h and h > 0 else None
                new_row[f"forward_dispersion_{h}"] = fwd_disp
                if fwd_disp is not None and row.get("bucket_return_dispersion") not in (None, 0):
                    new_row[f"forward_range_expansion_ratio_{h}"] = fwd_disp / row["bucket_return_dispersion"]
                else:
                    new_row[f"forward_range_expansion_ratio_{h}"] = None

                fwd_underlying = row.get(f"forward_underlying_return_{h}")
                if fwd_return is not None and fwd_underlying is not None:
                    new_row[f"forward_bucket_return_underlying_adjusted_{h}"] = fwd_return - fwd_underlying
                else:
                    new_row[f"forward_bucket_return_underlying_adjusted_{h}"] = None
            out.append(new_row)
    out.sort(key=lambda r: (r["option_id"], r["timestamp"]))
    return out


def build_bucket_panel(panel_rows: Sequence[dict], scheme: BucketScheme, *, horizons: tuple[int, ...] = HORIZONS) -> list[dict]:
    """The full Part 3-5 pipeline, entry point for the campaign."""
    table = build_bucket_day_table(panel_rows, scheme, horizons=horizons)
    feature_rows = build_feature_rows(table, scheme)
    return attach_forward_targets(feature_rows, horizons=horizons)
