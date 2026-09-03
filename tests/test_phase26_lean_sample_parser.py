"""Phase 26, Part 15 — parser correctness against real, verbatim rows
copied from the actually-downloaded QuantConnect/Lean sample this phase
fetched (logs/research_data/phase26_raw/), plus adversarial malformed
input."""

from __future__ import annotations

from datetime import date

import pytest

from src.options.phase26_lean_sample_parser import (
    parse_lean_equity_row,
    parse_lean_oi_row,
    parse_lean_option_filename,
    parse_lean_quote_row,
    parse_lean_trade_row,
)


def test_parses_real_daily_call_filename():
    m = parse_lean_option_filename("aapl_quote_american_call_1000000_20140613.csv")
    assert m.underlying_symbol == "AAPL"
    assert m.right == "call"
    assert m.strike == 100.0
    assert m.expiration == date(2014, 6, 13)
    assert m.tick_type == "quote"
    assert m.option_style == "american"
    assert m.file_date is None


def test_parses_real_minute_put_filename_with_leading_date():
    m = parse_lean_option_filename("20230803_spy_minute_quote_american_put_4700000_20230901.csv")
    assert m.underlying_symbol == "SPY"
    assert m.right == "put"
    assert m.strike == 470.0
    assert m.expiration == date(2023, 9, 1)
    assert m.file_date == date(2023, 8, 3)


def test_parses_real_openinterest_filename():
    m = parse_lean_option_filename("aapl_openinterest_american_call_10000000_20150117.csv")
    assert m.tick_type == "openinterest"
    assert m.strike == 1000.0


def test_rejects_a_filename_that_does_not_match_the_known_convention():
    with pytest.raises(ValueError):
        parse_lean_option_filename("not_a_real_filename.csv")


def test_parses_a_real_daily_quote_row():
    """Verbatim real row: AAPL $100 call exp 2016-01-15, quoted 2015-01-02."""
    row = parse_lean_quote_row("20150102 00:00,181000,186000,162000,175500,224,183500,203500,167000,177500,103", None)
    assert row.timestamp.isoformat() == "2015-01-02T00:00:00"
    assert row.bid_close == pytest.approx(17.55)
    assert row.ask_close == pytest.approx(17.75)
    assert row.last_bid_size == 224
    assert row.last_ask_size == 103
    assert row.is_daily_resolution is True


def test_parses_a_real_minute_quote_row_with_file_date():
    """Verbatim real row: SPY $430 call exp 2023-09-01, quoted 2023-08-03 at 9:30am (34200000 ms)."""
    row = parse_lean_quote_row("34200000,211900,221200,201900,221200,20,241900,251900,228600,231800,66", date(2023, 8, 3))
    assert row.timestamp.isoformat() == "2023-08-03T09:30:00"
    assert row.bid_close == pytest.approx(22.12)
    assert row.ask_close == pytest.approx(23.18)
    assert row.is_daily_resolution is False


def test_parses_a_real_one_sided_market_row_without_crashing():
    """A REAL row this phase found: 2014-06-06, a deep-OTM AAPL call had
    no bid quoted at all (empty field), only an ask -- must parse as
    None, never 0.0 (see phase26_lean_sample_parser's
    `_parse_optional_decicents` docstring)."""
    row = parse_lean_quote_row("20140606 00:00,,,,,0,300,300,100,100,199", None)
    assert row.bid_open is None
    assert row.bid_high is None
    assert row.bid_low is None
    assert row.bid_close is None
    assert row.last_bid_size == 0
    assert row.ask_close == pytest.approx(0.01)


def test_parses_a_real_trade_row():
    row = parse_lean_trade_row("37380000,223300,223300,223300,223300,1", date(2023, 8, 3))
    assert row.close == pytest.approx(22.33)
    assert row.volume == 1
    assert row.is_daily_resolution is False


def test_parses_a_real_openinterest_row():
    row = parse_lean_oi_row("20140606 00:00,9325", None)
    assert row.open_interest == 9325
    assert row.is_daily_resolution is True


def test_parses_a_real_equity_row_matching_known_aapl_close():
    """AAPL's real closing price on 2015-01-02 is publicly known to be
    $109.33 -- this is an independent cross-check, not a tautology."""
    bar = parse_lean_equity_row("20150102 00:00,1114100,1114400,1073500,1093300,52381530")
    assert bar.close == pytest.approx(109.33)
    assert bar.date == date(2015, 1, 2)
    assert bar.volume == 52381530


def test_quote_row_rejects_wrong_column_count():
    with pytest.raises(ValueError):
        parse_lean_quote_row("1,2,3", None)


def test_trade_row_rejects_wrong_column_count():
    with pytest.raises(ValueError):
        parse_lean_trade_row("1,2,3,4", None)


def test_minute_row_without_file_date_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        parse_lean_quote_row("34200000,1,1,1,1,1,1,1,1,1,1", None)
