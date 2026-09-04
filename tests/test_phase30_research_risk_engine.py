"""Phase 30, Part 8/17 — the research portfolio risk-engine interface."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.options.instrument import OptionContract
from src.options.position import OptionLegPosition, OptionsPosition
from src.options.research_dataset import DataQualityStatus, build_research_observations
from src.options.research_position_view import build_position_snapshot
from src.options.research_risk_engine import ResearchRiskLimits, assess_portfolio_risk
from tests.phase30_fixtures import synthetic_store

OPENED = datetime(2026, 1, 1, tzinfo=timezone.utc)
AS_OF = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _contract(option_id, call_put="call", strike=100.0, underlying="AAPL"):
    return OptionContract(underlying_symbol=underlying, option_id=option_id, call_put=call_put, strike=strike, expiration=date(2026, 12, 18))


def _snapshot(option_id="c1", underlying="AAPL", side="long", mark=7.0, entry=5.0):
    leg = OptionLegPosition(contract=_contract(option_id, underlying=underlying), side=side, quantity=1, entry_price=entry, entry_timestamp=OPENED)
    pos = OptionsPosition(legs=(leg,), opened_at=OPENED)
    return build_position_snapshot(pos, current_marks={option_id: mark}, as_of=AS_OF)


def test_unconfigured_limits_never_fail_and_report_not_configured():
    snap = _snapshot()
    result = assess_portfolio_risk([snap], account_equity_usd=1000.0)
    assert result.any_check_failed is False
    assert all("NOT_CONFIGURED" in r.message or r.passed for r in result.results)


def test_capital_at_risk_pct_computed_correctly():
    snap = _snapshot(mark=7.0, entry=5.0)  # long call, max_loss = 5.0*100 = 500
    result = assess_portfolio_risk([snap], account_equity_usd=1000.0)
    assert result.total_capital_at_risk_usd == 500.0
    assert result.capital_at_risk_pct == 0.5
    assert result.capital_at_risk_is_partial is False


def test_capital_at_risk_limit_can_fail():
    snap = _snapshot(mark=7.0, entry=5.0)
    limits = ResearchRiskLimits(max_capital_at_risk_pct=0.1)
    result = assess_portfolio_risk([snap], account_equity_usd=1000.0, limits=limits)
    assert result.any_check_failed is True
    assert "CAPITAL_AT_RISK" in result.failing_codes


def test_undetermined_risk_never_silently_passes_as_zero():
    """A naked short call has max_loss=None (unbounded) -- the portfolio
    must flag capital_at_risk_is_partial, never silently treat it as
    zero risk."""
    leg = OptionLegPosition(contract=_contract("c1", call_put="call"), side="short", quantity=1, entry_price=2.0, entry_timestamp=OPENED)
    pos = OptionsPosition(legs=(leg,), opened_at=OPENED)
    snap = build_position_snapshot(pos, current_marks={"c1": 3.0}, as_of=AS_OF)
    result = assess_portfolio_risk([snap], account_equity_usd=1000.0)
    assert result.capital_at_risk_is_partial is True


def test_underlying_concentration_full_when_single_position():
    snap = _snapshot(underlying="AAPL")
    result = assess_portfolio_risk([snap], account_equity_usd=1000.0)
    assert result.underlying_concentration_pct["AAPL"] == 1.0


def test_underlying_concentration_limit_can_fail():
    snap = _snapshot(underlying="AAPL")
    limits = ResearchRiskLimits(max_single_underlying_concentration_pct=0.5)
    result = assess_portfolio_risk([snap], account_equity_usd=1000.0, limits=limits)
    assert "UNDERLYING_CONCENTRATION" in result.failing_codes


def test_correlated_group_concentration():
    snap_a = _snapshot(option_id="c1", underlying="AAPL")
    snap_b = _snapshot(option_id="c2", underlying="MSFT")
    result = assess_portfolio_risk(
        [snap_a, snap_b], account_equity_usd=2000.0,
        correlated_groups={"AAPL": "TECH", "MSFT": "TECH"},
    )
    assert result.correlated_group_concentration_pct["TECH"] == 1.0


def test_liquidity_checks_use_referenced_observations():
    store = synthetic_store()
    rows = build_research_observations(store)
    cid = rows[0].option_id
    leg = OptionLegPosition(contract=_contract(cid, underlying="AAPL"), side="long", quantity=1, entry_price=4.9, entry_timestamp=OPENED)
    pos = OptionsPosition(legs=(leg,), opened_at=OPENED)
    snap = build_position_snapshot(pos, current_marks={cid: 5.0}, as_of=AS_OF)
    limits = ResearchRiskLimits(min_liquidity_volume=1000.0)
    result = assess_portfolio_risk([snap], account_equity_usd=1000.0, limits=limits, liquidity_by_contract={cid: rows[0]})
    assert "LIQUIDITY_VOLUME" in result.failing_codes


def test_data_quality_rejection():
    store = synthetic_store()
    rows = build_research_observations(store)
    cid = rows[0].option_id
    import dataclasses
    poisoned = dataclasses.replace(rows[0], data_quality=DataQualityStatus.FLAGGED_CRITICAL)
    leg = OptionLegPosition(contract=_contract(cid, underlying="AAPL"), side="long", quantity=1, entry_price=4.9, entry_timestamp=OPENED)
    pos = OptionsPosition(legs=(leg,), opened_at=OPENED)
    snap = build_position_snapshot(pos, current_marks={cid: 5.0}, as_of=AS_OF)
    result = assess_portfolio_risk([snap], account_equity_usd=1000.0, liquidity_by_contract={cid: poisoned})
    assert "DATA_QUALITY" in result.failing_codes


def test_assignment_exercise_risk_flags_short_itm_near_expiration():
    leg = OptionLegPosition(contract=_contract("c1", call_put="call", strike=100.0), side="short", quantity=1, entry_price=2.0, entry_timestamp=OPENED)
    pos = OptionsPosition(legs=(leg,), opened_at=OPENED)
    near_expiry = datetime(2026, 12, 17, tzinfo=timezone.utc)
    snap = build_position_snapshot(pos, current_marks={"c1": 12.0}, as_of=near_expiry)
    limits = ResearchRiskLimits(assignment_risk_dte_threshold=5)
    result = assess_portfolio_risk([snap], account_equity_usd=1000.0, limits=limits, underlying_prices={"AAPL": 115.0})
    assert "ASSIGNMENT_EXERCISE_RISK" in result.failing_codes


def test_empty_portfolio_never_crashes():
    result = assess_portfolio_risk([], account_equity_usd=1000.0)
    assert result.position_count == 0
    assert result.any_check_failed is False
