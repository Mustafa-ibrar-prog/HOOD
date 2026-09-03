"""Phase 20, Part 13/24 — option return normalization tests, including
causal (no-lookahead) MAE/MFE."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.options.price_history import OptionPriceBar
from src.options.return_normalization import compute_normalized_return


def _bars(rows: list[tuple[float, float, float, float]]) -> list[OptionPriceBar]:
    start = date(2022, 1, 3)
    return [OptionPriceBar(date=start + timedelta(days=i), open=o, high=h, low=l, close=c) for i, (o, h, l, c) in enumerate(rows)]


def test_raw_percentage_return():
    window = _bars([(5.0, 5.0, 5.0, 5.0), (6.0, 6.0, 6.0, 6.0)])
    result = compute_normalized_return(window)
    assert result.raw_percentage_return == pytest.approx(0.2)


def test_dollar_return_per_contract_uses_multiplier():
    window = _bars([(5.0, 5.0, 5.0, 5.0), (6.0, 6.0, 6.0, 6.0)])
    result = compute_normalized_return(window, contract_multiplier=100)
    assert result.dollar_return_per_contract == pytest.approx(100.0)


def test_return_relative_to_premium_matches_raw_return():
    window = _bars([(5.0, 5.0, 5.0, 5.0), (6.0, 6.0, 6.0, 6.0)])
    result = compute_normalized_return(window)
    assert result.return_relative_to_premium == pytest.approx(result.raw_percentage_return)


def test_rejects_empty_window():
    with pytest.raises(ValueError):
        compute_normalized_return([])


def test_rejects_nonpositive_entry():
    window = _bars([(0.0, 0.0, 0.0, 0.0), (1.0, 1.0, 1.0, 1.0)])
    with pytest.raises(ValueError):
        compute_normalized_return(window)


def test_mae_mfe_causal_window_only():
    """entry=5, path dips to 3 (low) then rallies to 9 (high) then exits
    at 7 -- MAE/MFE must reflect the PATH within the window, not just
    entry/exit."""
    window = _bars([(5.0, 5.0, 5.0, 5.0), (4.0, 4.5, 3.0, 4.0), (8.0, 9.0, 7.5, 7.0)])
    result = compute_normalized_return(window)
    assert result.max_adverse_excursion == pytest.approx((5.0 - 3.0) / 5.0)
    assert result.max_favorable_excursion == pytest.approx((9.0 - 5.0) / 5.0)
    assert result.payoff_asymmetry == pytest.approx(result.max_favorable_excursion - result.max_adverse_excursion)


def test_mae_mfe_never_negative():
    """A path that never goes below/above entry should report 0.0, not a
    negative excursion."""
    window = _bars([(5.0, 5.0, 5.0, 5.0), (5.5, 6.0, 5.2, 5.8)])  # always at/above entry
    result = compute_normalized_return(window)
    assert result.max_adverse_excursion == 0.0
    assert result.max_favorable_excursion == pytest.approx((6.0 - 5.0) / 5.0)


def test_mae_mfe_ignore_bars_beyond_the_given_window():
    """Structural no-lookahead proof: a window sliced to [entry, exit]
    must not be influenced by bars the caller didn't include."""
    full_window = _bars([(5.0, 5.0, 5.0, 5.0), (4.0, 4.0, 4.0, 4.0), (100.0, 100.0, 100.0, 100.0)])
    truncated = full_window[:2]  # exclude the bar with the extreme high
    result = compute_normalized_return(truncated)
    assert result.max_favorable_excursion == 0.0  # never saw the 100.0 high
