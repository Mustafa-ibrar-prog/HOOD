"""Phase 7, Part 9 & 19: regime-conditional cross-sectional IC tests —
the src.research.regime.ic_by_regime function the Phase 4 ic.py docstring
has referenced since it was written but never implemented until now."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.research.regime import ic_by_regime

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_ic_by_regime_buckets_correctly_and_computes_per_bucket_ic():
    regime_labels = {}
    rows = []
    for t in range(20):
        ts = T0 + timedelta(days=t)
        regime = "bull_low_vol" if t < 10 else "bear_high_vol"
        regime_labels[ts] = regime
        for s in range(6):
            rows.append({"timestamp": ts, "symbol": f"SYM{s}", "f": float(s), "tgt": float(s) * 2})

    result = ic_by_regime(rows, "f", "tgt", regime_labels)
    assert set(result.keys()) == {"bull_low_vol", "bear_high_vol"}
    assert result["bull_low_vol"].average_ic == 1.0
    assert result["bear_high_vol"].average_ic == 1.0


def test_ic_by_regime_uses_the_rows_own_timestamp_not_a_later_one():
    """A row bucketed at t must use the regime active AT t, never a
    regime label from a later timestamp — causal bucketing, same
    principle as bucket_trades_by_regime."""
    ts_early = T0
    ts_late = T0 + timedelta(days=100)
    regime_labels = {ts_early: "bull_low_vol", ts_late: "bear_high_vol"}
    rows = [
        {"timestamp": ts_early, "symbol": "A", "f": 1.0, "tgt": 1.0},
        {"timestamp": ts_early, "symbol": "B", "f": 2.0, "tgt": 2.0},
        {"timestamp": ts_early, "symbol": "C", "f": 3.0, "tgt": 3.0},
    ]
    result = ic_by_regime(rows, "f", "tgt", regime_labels)
    assert "bull_low_vol" in result
    assert "bear_high_vol" not in result  # nothing was ever labeled at ts_late


def test_ic_by_regime_unknown_bucket_for_untracked_timestamps():
    rows = [
        {"timestamp": T0, "symbol": "A", "f": 1.0, "tgt": 1.0},
        {"timestamp": T0, "symbol": "B", "f": 2.0, "tgt": 2.0},
        {"timestamp": T0, "symbol": "C", "f": 3.0, "tgt": 3.0},
    ]
    result = ic_by_regime(rows, "f", "tgt", {})  # no regime labels at all
    assert "unknown" in result


def test_ic_by_regime_distinguishes_broad_from_narrow_regime_effects():
    """The Part-9 requirement in miniature: a feature that works in EVERY
    regime looks different from one that only works in one."""
    regime_labels = {}
    broad_rows, narrow_rows = [], []
    for t in range(30):
        ts = T0 + timedelta(days=t)
        regime = ["bull_low_vol", "bull_high_vol", "bear_low_vol"][t % 3]
        regime_labels[ts] = regime
        for s in range(6):
            broad_rows.append({"timestamp": ts, "symbol": f"SYM{s}", "f": float(s), "tgt": float(s)})  # perfect in every regime
            narrow_target = float(s) if regime == "bull_low_vol" else float(5 - s)  # inverted outside one regime
            narrow_rows.append({"timestamp": ts, "symbol": f"SYM{s}", "f": float(s), "tgt": narrow_target})

    broad_result = ic_by_regime(broad_rows, "f", "tgt", regime_labels)
    narrow_result = ic_by_regime(narrow_rows, "f", "tgt", regime_labels)

    assert all(v.average_ic == 1.0 for v in broad_result.values())
    assert narrow_result["bull_low_vol"].average_ic == 1.0
    assert narrow_result["bull_high_vol"].average_ic == -1.0
    assert narrow_result["bear_low_vol"].average_ic == -1.0
