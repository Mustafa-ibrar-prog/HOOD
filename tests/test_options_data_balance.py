"""Phase 20, Part 7/24 — data-balance / concentration tests."""

from __future__ import annotations

from datetime import date

from src.options.data_balance import build_data_balance_report, compute_concentration


def test_compute_concentration_basic():
    result = compute_concentration(["A", "A", "A", "A", "B"], dimension="symbol")
    assert result.total_observations == 5
    assert result.top_key == "A"
    assert result.top_key_share == 0.8


def test_compute_concentration_empty():
    result = compute_concentration([], dimension="symbol")
    assert result.total_observations == 0
    assert result.top_key is None
    assert result.top_key_share == 0.0


def test_part7_worked_example_80_percent_nvda():
    """Part 7's own example: 'If 80% of observations come from NVDA, the
    research must NOT be described as broadly diversified.'"""
    values = ["NVDA"] * 8 + ["AAPL"] * 2
    result = compute_concentration(values, dimension="symbol")
    assert result.top_key == "NVDA"
    assert result.top_key_share == 0.8


def _row(symbol, expiration, bucket, call_put, year):
    return {"underlying_symbol": symbol, "expiration": expiration, "moneyness_bucket": bucket, "call_put": call_put, "timestamp": date(year, 1, 1)}


def test_build_data_balance_report():
    rows = [
        _row("AAPL", "2022-06-17", "itm", "call", 2022),
        _row("AAPL", "2022-06-17", "otm", "put", 2022),
        _row("NVDA", "2023-06-16", "itm", "call", 2023),
    ]
    sector_by_symbol = {"AAPL": "technology", "NVDA": "technology"}
    report = build_data_balance_report(rows, sector_by_symbol=sector_by_symbol)
    assert report.symbol_concentration.top_key == "AAPL"
    assert report.sector_concentration.top_key == "technology"
    assert report.sector_concentration.top_key_share == 1.0
    assert report.expiration_concentration.total_observations == 3
    assert report.call_put_concentration.counts_by_key == {"call": 2, "put": 1}
    assert report.year_concentration.counts_by_key == {"2022": 2, "2023": 1}
    assert "symbol" in report.render()


def test_build_data_balance_report_unclassified_sector():
    rows = [_row("XYZ", "2022-06-17", "itm", "call", 2022)]
    report = build_data_balance_report(rows, sector_by_symbol={})
    assert report.sector_concentration.top_key == "unclassified"
