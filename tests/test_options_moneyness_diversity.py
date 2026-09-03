"""Phase 20, Part 6/24 — moneyness diversity reporting tests."""

from __future__ import annotations

from src.options.moneyness import MoneynessBucket
from src.options.moneyness_diversity import build_moneyness_diversity_report


def _row(option_id, bucket, dte):
    return {"option_id": option_id, "moneyness_bucket": bucket, "dte": dte}


def test_diversity_report_basic_shares():
    rows = [
        _row("c1", "itm", 10), _row("c1", "itm", 9),
        _row("c2", "otm", 10), _row("c2", "otm", 9), _row("c2", "otm", 8), _row("c2", "otm", 7),
    ]
    report = build_moneyness_diversity_report("AAPL", rows)
    itm = next(b for b in report.buckets if b.bucket == MoneynessBucket.ITM)
    otm = next(b for b in report.buckets if b.bucket == MoneynessBucket.OTM)
    assert itm.observation_count == 2
    assert otm.observation_count == 4
    assert itm.share_of_sample == 2 / 6
    assert otm.share_of_sample == 4 / 6
    assert report.most_represented_bucket == MoneynessBucket.OTM
    assert report.is_concentrated is True  # OTM holds 4/6 = 66.7% > 50%


def test_is_concentrated_true_over_50_percent():
    rows = [_row("c1", "deep_otm", 5)] * 6 + [_row("c2", "itm", 5)] * 2
    report = build_moneyness_diversity_report("AAPL", rows)
    assert report.is_concentrated is True


def test_average_dte_computed_per_bucket():
    rows = [_row("c1", "itm", 10), _row("c1", "itm", 20)]
    report = build_moneyness_diversity_report("AAPL", rows)
    itm = next(b for b in report.buckets if b.bucket == MoneynessBucket.ITM)
    assert itm.average_dte == 15.0


def test_incomplete_history_fraction():
    rows = [_row("c1", "itm", 10), _row("c2", "itm", 10)]
    report = build_moneyness_diversity_report("AAPL", rows, incomplete_contract_ids=frozenset({"c1"}))
    itm = next(b for b in report.buckets if b.bucket == MoneynessBucket.ITM)
    assert itm.incomplete_history_fraction == 0.5


def test_empty_report():
    report = build_moneyness_diversity_report("AAPL", [])
    assert report.buckets == ()
    assert report.most_represented_bucket is None
    assert report.is_concentrated is False
