"""Phase 30, Part 7/17 — the expanded, reporting-ready position view."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.options.greeks import GreeksProvenance
from src.options.instrument import OptionContract
from src.options.position import OptionLegPosition, OptionsPosition
from src.options.research_position_view import build_position_snapshot, classify_structure

OPENED = datetime(2026, 1, 1, tzinfo=timezone.utc)
AS_OF = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _contract(option_id="c1", call_put="call", strike=100.0, expiration=date(2026, 12, 18), underlying="AAPL"):
    return OptionContract(underlying_symbol=underlying, option_id=option_id, call_put=call_put, strike=strike, expiration=expiration)


def test_long_call_structure_and_fields():
    leg = OptionLegPosition(contract=_contract(), side="long", quantity=2, entry_price=5.0, entry_timestamp=OPENED)
    pos = OptionsPosition(legs=(leg,), opened_at=OPENED, strategy_label="test")
    snap = build_position_snapshot(pos, current_marks={"c1": 7.0}, as_of=AS_OF, underlying_prices={"AAPL": 110.0})
    assert snap.structure == "LONG_CALL"
    assert snap.market_value == 7.0 * 2 * 100
    assert snap.unrealized_pnl == (7.0 - 5.0) * 2 * 100
    assert snap.max_loss == 5.0 * 2 * 100
    assert snap.max_gain is None  # unbounded upside
    assert snap.is_defined_risk is True
    assert snap.legs[0].dte == (date(2026, 12, 18) - date(2026, 6, 1)).days


def test_short_put_structure():
    leg = OptionLegPosition(contract=_contract(call_put="put"), side="short", quantity=1, entry_price=3.0, entry_timestamp=OPENED)
    pos = OptionsPosition(legs=(leg,), opened_at=OPENED)
    snap = build_position_snapshot(pos, current_marks={"c1": 2.0}, as_of=AS_OF)
    assert snap.structure == "SHORT_PUT"
    assert snap.max_gain == 3.0 * 100


def test_vertical_spread_structure():
    long_leg = OptionLegPosition(contract=_contract(option_id="c1", strike=100.0), side="long", quantity=1, entry_price=5.0, entry_timestamp=OPENED)
    short_leg = OptionLegPosition(contract=_contract(option_id="c2", strike=110.0), side="short", quantity=1, entry_price=2.0, entry_timestamp=OPENED)
    pos = OptionsPosition(legs=(long_leg, short_leg), opened_at=OPENED)
    snap = build_position_snapshot(pos, current_marks={"c1": 6.0, "c2": 1.5}, as_of=AS_OF)
    assert snap.structure == "VERTICAL_SPREAD"
    assert snap.max_loss is not None and snap.max_gain is not None
    assert snap.is_defined_risk is True


def test_unsupported_structure_never_guesses():
    legs = tuple(
        OptionLegPosition(contract=_contract(option_id=f"c{i}", strike=100.0 + i * 5), side="long", quantity=1, entry_price=1.0, entry_timestamp=OPENED)
        for i in range(3)
    )
    pos = OptionsPosition(legs=legs, opened_at=OPENED)
    snap = build_position_snapshot(pos, current_marks={f"c{i}": 1.0 for i in range(3)}, as_of=AS_OF)
    assert snap.structure == "UNSUPPORTED_STRUCTURE"
    assert snap.max_loss is None
    assert snap.max_gain is None
    assert snap.is_defined_risk is False
    assert "UNSUPPORTED_STRUCTURE" in snap.risk_method


def test_missing_mark_yields_none_market_value_and_unrealized_pnl():
    leg = OptionLegPosition(contract=_contract(), side="long", quantity=1, entry_price=5.0, entry_timestamp=OPENED)
    pos = OptionsPosition(legs=(leg,), opened_at=OPENED)
    snap = build_position_snapshot(pos, current_marks={}, as_of=AS_OF)
    assert snap.market_value is None
    assert snap.unrealized_pnl is None
    assert snap.legs[0].current_mark is None


def test_greeks_reconstructed_when_mark_and_underlying_available():
    leg = OptionLegPosition(contract=_contract(), side="long", quantity=1, entry_price=5.0, entry_timestamp=OPENED)
    pos = OptionsPosition(legs=(leg,), opened_at=OPENED)
    snap = build_position_snapshot(pos, current_marks={"c1": 15.0}, as_of=AS_OF, underlying_prices={"AAPL": 110.0})
    g = snap.legs[0].greeks
    assert g.provenance == GreeksProvenance.DERIVED_FROM_MODEL
    assert g.delta is not None
    assert g.derived_metadata is not None
    assert g.derived_metadata.model == "black_scholes"


def test_greeks_unavailable_without_underlying_price():
    leg = OptionLegPosition(contract=_contract(), side="long", quantity=1, entry_price=5.0, entry_timestamp=OPENED)
    pos = OptionsPosition(legs=(leg,), opened_at=OPENED)
    snap = build_position_snapshot(pos, current_marks={"c1": 7.0}, as_of=AS_OF)
    assert snap.legs[0].greeks.provenance == GreeksProvenance.UNAVAILABLE
    assert snap.legs[0].greeks.delta is None


def test_realized_pnl_defaults_to_zero_and_is_passed_through():
    leg = OptionLegPosition(contract=_contract(), side="long", quantity=1, entry_price=5.0, entry_timestamp=OPENED)
    pos = OptionsPosition(legs=(leg,), opened_at=OPENED)
    snap = build_position_snapshot(pos, current_marks={"c1": 7.0}, as_of=AS_OF)
    assert snap.realized_pnl == 0.0
    snap2 = build_position_snapshot(pos, current_marks={"c1": 7.0}, as_of=AS_OF, realized_pnl=123.45)
    assert snap2.realized_pnl == 123.45


def test_classify_structure_matches_snapshot_structure():
    leg = OptionLegPosition(contract=_contract(call_put="put"), side="long", quantity=1, entry_price=1.0, entry_timestamp=OPENED)
    pos = OptionsPosition(legs=(leg,), opened_at=OPENED)
    assert classify_structure(pos) == "LONG_PUT"
