"""Phase 13, Part 5, 7, 28: overnight/intraday feature tests —
no-lookahead (mirrors tests/test_feature_no_lookahead.py's methodology),
targeted correctness, and the mandatory identity test (Part 5).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.bar import Bar
from src.features.overnight_intraday import (
    AbsIntradayReturn,
    AbsOvernightReturn,
    GapExtremeness,
    IntradayExtremeness,
    IntradayReturn,
    OvernightIntradayDisagreement,
    OvernightIntradayInteraction,
    OvernightIntradayState,
    OvernightReturn,
)

CUTOFF = 100
TOTAL = 160


def _base_bars() -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    close = 100.0
    for i in range(TOTAL):
        open_ = close * (1 + (0.004 if i % 4 else -0.006))  # overnight gap
        close = open_ * (1 + (0.003 if i % 3 else -0.005))  # intraday move
        high = max(open_, close) + 0.3
        low = min(open_, close) - 0.3
        bars.append(Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=open_, high=high, low=low, close=close, volume=1000))
    return bars


def _mutated_future(bars: list[Bar]) -> list[Bar]:
    out = list(bars[: CUTOFF + 1])
    start = bars[CUTOFF].timestamp
    for i in range(CUTOFF + 1, TOTAL):
        out.append(Bar(timestamp=start + timedelta(days=i - CUTOFF), symbol="AAPL", timeframe="day", open=1e9, high=2e9, low=5e8, close=1.5e9, volume=999_999_999))
    return out


FEATURES = [
    OvernightReturn(), IntradayReturn(), AbsOvernightReturn(), AbsIntradayReturn(),
    OvernightIntradayDisagreement(), GapExtremeness(20), IntradayExtremeness(20),
    OvernightIntradayState(), OvernightIntradayInteraction(),
]


@pytest.mark.parametrize("feature", FEATURES, ids=lambda f: f.spec.name)
def test_feature_does_not_leak_future_data(feature):
    base = _base_bars()
    mutated = _mutated_future(base)
    values_base = feature.compute(base)
    values_mutated = feature.compute(mutated)
    for i in range(CUTOFF + 1):
        assert values_base[i] == values_mutated[i], f"{feature.spec.name} leaked future data at index {i}"


# --- the mandatory identity test (Part 5) -----------------------------------------------------


def test_overnight_intraday_identity_matches_close_to_close():
    """(1 + overnight_t) * (1 + intraday_t) - 1 == close_to_close_t,
    within numerical tolerance — verified independently of
    scripts/phase13_step0_data_quality_gate.py's real-data check."""
    bars = _base_bars()
    overnight = OvernightReturn().compute(bars)
    intraday = IntradayReturn().compute(bars)
    for i in range(1, len(bars)):
        o, intr = overnight[i], intraday[i]
        assert o is not None and intr is not None
        reconstructed = (1 + o) * (1 + intr) - 1
        close_to_close = bars[i].close / bars[i - 1].close - 1
        assert abs(reconstructed - close_to_close) < 1e-9


def test_overnight_return_is_none_at_index_zero_and_matches_hand_computed():
    bars = _base_bars()
    overnight = OvernightReturn().compute(bars)
    assert overnight[0] is None
    expected = bars[1].open / bars[0].close - 1
    assert overnight[1] is not None and abs(overnight[1] - expected) < 1e-12


def test_intraday_return_hand_computed():
    bars = _base_bars()
    intraday = IntradayReturn().compute(bars)
    expected = bars[0].close / bars[0].open - 1
    assert intraday[0] is not None and abs(intraday[0] - expected) < 1e-12


def test_abs_features_match_abs_of_signed():
    bars = _base_bars()
    overnight, abs_overnight = OvernightReturn().compute(bars), AbsOvernightReturn().compute(bars)
    for o, a in zip(overnight, abs_overnight):
        if o is None:
            assert a is None
        else:
            assert a is not None and abs(a - abs(o)) < 1e-12


def test_disagreement_flag_hand_computed():
    """overnight=+, intraday=- -> disagreement; overnight=+, intraday=+ -> no disagreement."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = [
        Bar(timestamp=start, symbol="X", timeframe="day", open=100, high=101, low=99, close=100, volume=1000),
        Bar(timestamp=start + timedelta(days=1), symbol="X", timeframe="day", open=105, high=106, low=100, close=100, volume=1000),  # overnight=+5%, intraday=-4.76% -> disagree
        Bar(timestamp=start + timedelta(days=2), symbol="X", timeframe="day", open=102, high=110, low=101, close=108, volume=1000),  # overnight=+2%, intraday=+5.88% -> agree
    ]
    disagreement = OvernightIntradayDisagreement().compute(bars)
    assert disagreement[1] == 1.0
    assert disagreement[2] == 0.0


def test_state_hand_computed_all_four_quadrants():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = [
        Bar(timestamp=start, symbol="X", timeframe="day", open=100, high=101, low=99, close=100, volume=1000),
        Bar(timestamp=start + timedelta(days=1), symbol="X", timeframe="day", open=102, high=110, low=101, close=108, volume=1000),  # overnight=+, intraday=+ -> 0
        Bar(timestamp=start + timedelta(days=2), symbol="X", timeframe="day", open=112, high=113, low=100, close=100, volume=1000),  # overnight=+, intraday=- -> 1
        Bar(timestamp=start + timedelta(days=3), symbol="X", timeframe="day", open=95, high=105, low=94, close=104, volume=1000),  # overnight=-, intraday=+ -> 2
        Bar(timestamp=start + timedelta(days=4), symbol="X", timeframe="day", open=100, high=101, low=90, close=92, volume=1000),  # overnight=-, intraday=- -> 3
    ]
    state = OvernightIntradayState().compute(bars)
    assert state[1:] == [0.0, 1.0, 2.0, 3.0]
    assert OvernightIntradayState.label_for(0.0) == "+/+"
    assert OvernightIntradayState.label_for(3.0) == "-/-"
    assert OvernightIntradayState.label_for(None) is None


def test_interaction_matches_product():
    bars = _base_bars()
    overnight, intraday = OvernightReturn().compute(bars), IntradayReturn().compute(bars)
    interaction = OvernightIntradayInteraction().compute(bars)
    for o, i, x in zip(overnight, intraday, interaction):
        if o is None or i is None:
            assert x is None
        else:
            assert x is not None and abs(x - o * i) < 1e-12


def test_gap_extremeness_excludes_current_bar_from_baseline():
    """GapExtremeness at bar t must use volatility computed through
    t-1 — a manual check that shifting the raw vol series by one
    reproduces exactly what the feature does."""
    from src.features.volatility import RealizedVolatility

    bars = _base_bars()
    raw_vol = RealizedVolatility(20).compute(bars)
    overnight = OvernightReturn().compute(bars)
    gap_extreme = GapExtremeness(20).compute(bars)
    for i in range(1, len(bars)):
        lagged_vol = raw_vol[i - 1]
        if overnight[i] is None or lagged_vol is None or lagged_vol == 0:
            assert gap_extreme[i] is None
        else:
            assert gap_extreme[i] is not None and abs(gap_extreme[i] - overnight[i] / lagged_vol) < 1e-9


def test_invalid_params_rejected():
    with pytest.raises(ValueError):
        GapExtremeness(vol_window=1)
    with pytest.raises(ValueError):
        IntradayExtremeness(vol_window=0)
