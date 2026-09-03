"""Phase 26, Part 7/15 — Black-Scholes solver correctness: known
analytical properties, put-call parity, and a round-trip (price ->
implied vol -> recovered price) using the real AAPL example this phase
found."""

from __future__ import annotations

import math
from datetime import date

import pytest

from src.options.black_scholes import (
    BlackScholesInputs,
    black_scholes_greeks,
    black_scholes_price,
    implied_volatility_bisection,
)


def test_call_price_matches_a_known_textbook_value():
    """Hull's textbook example: S=42, K=40, r=10%, sigma=20%, T=0.5,
    q=0 -> call price approx 4.76."""
    inputs = BlackScholesInputs(underlying_price=42, strike=40, time_to_expiration_years=0.5, risk_free_rate=0.10, volatility=0.20)
    price = black_scholes_price(inputs, call_put="call")
    assert price == pytest.approx(4.76, abs=0.01)


def test_put_call_parity_holds():
    inputs = BlackScholesInputs(underlying_price=100, strike=95, time_to_expiration_years=1.0, risk_free_rate=0.03, volatility=0.25, dividend_yield=0.01)
    call = black_scholes_price(inputs, call_put="call")
    put = black_scholes_price(inputs, call_put="put")
    s, k, t, r, q = 100, 95, 1.0, 0.03, 0.01
    lhs = call - put
    rhs = s * math.exp(-q * t) - k * math.exp(-r * t)
    assert lhs == pytest.approx(rhs, abs=1e-8)


def test_call_price_increases_with_volatility():
    low = BlackScholesInputs(100, 100, 1.0, 0.02, 0.10)
    high = BlackScholesInputs(100, 100, 1.0, 0.02, 0.40)
    assert black_scholes_price(high, call_put="call") > black_scholes_price(low, call_put="call")


def test_deep_itm_call_delta_approaches_one():
    inputs = BlackScholesInputs(underlying_price=300, strike=50, time_to_expiration_years=0.1, risk_free_rate=0.02, volatility=0.2)
    g = black_scholes_greeks(inputs, call_put="call")
    assert g.delta > 0.99


def test_deep_otm_put_delta_approaches_zero():
    inputs = BlackScholesInputs(underlying_price=300, strike=50, time_to_expiration_years=0.1, risk_free_rate=0.02, volatility=0.2)
    g = black_scholes_greeks(inputs, call_put="put")
    assert g.delta > -0.01


def test_gamma_is_identical_for_call_and_put_at_same_strike():
    inputs = BlackScholesInputs(underlying_price=100, strike=105, time_to_expiration_years=0.5, risk_free_rate=0.02, volatility=0.3)
    gc = black_scholes_greeks(inputs, call_put="call")
    gp = black_scholes_greeks(inputs, call_put="put")
    assert gc.gamma == pytest.approx(gp.gamma)
    assert gc.vega == pytest.approx(gp.vega)


def test_implied_volatility_round_trip_recovers_the_input_vol():
    true_vol = 0.35
    inputs = BlackScholesInputs(underlying_price=150, strike=140, time_to_expiration_years=0.75, risk_free_rate=0.02, volatility=true_vol, dividend_yield=0.01)
    price = black_scholes_price(inputs, call_put="call")
    solved = implied_volatility_bisection(
        target_price=price, underlying_price=150, strike=140, time_to_expiration_years=0.75,
        risk_free_rate=0.02, dividend_yield=0.01, call_put="call",
    )
    assert solved == pytest.approx(true_vol, abs=1e-4)


def test_real_aapl_example_recovers_a_plausible_iv():
    """Real AAPL data this phase ingested: 2015-01-02 close=$109.33
    (verified real), AAPL_call_100_2016-01-15 mid quote=$17.65 (verified
    real). The recovered IV must be a plausible equity-option value
    (AAPL's real historical IV in this period was well within 15%-60%)."""
    t_years = (date(2016, 1, 15) - date(2015, 1, 2)).days / 365.0
    iv = implied_volatility_bisection(
        target_price=17.65, underlying_price=109.33, strike=100.0, time_to_expiration_years=t_years,
        risk_free_rate=0.02, dividend_yield=0.015, call_put="call",
    )
    assert iv is not None
    assert 0.15 < iv < 0.60


def test_implied_volatility_returns_none_rather_than_a_fabricated_value_when_unsolvable():
    """A target price above what any positive volatility can produce
    (e.g. above the underlying itself for a deep ITM call beyond
    intrinsic+extreme-vol bound) must return None, never a clamped
    fake number."""
    solved = implied_volatility_bisection(
        target_price=10_000.0, underlying_price=100, strike=100, time_to_expiration_years=0.1,
        risk_free_rate=0.02, dividend_yield=0.0, call_put="call", high=5.0,
    )
    assert solved is None


def test_black_scholes_inputs_rejects_non_positive_values():
    with pytest.raises(ValueError):
        BlackScholesInputs(underlying_price=-1, strike=100, time_to_expiration_years=1, risk_free_rate=0.02, volatility=0.2)
    with pytest.raises(ValueError):
        BlackScholesInputs(underlying_price=100, strike=100, time_to_expiration_years=0, risk_free_rate=0.02, volatility=0.2)
    with pytest.raises(ValueError):
        BlackScholesInputs(underlying_price=100, strike=100, time_to_expiration_years=1, risk_free_rate=0.02, volatility=0)


def test_invalid_call_put_raises():
    inputs = BlackScholesInputs(100, 100, 1, 0.02, 0.2)
    with pytest.raises(ValueError):
        black_scholes_price(inputs, call_put="not_a_side")
