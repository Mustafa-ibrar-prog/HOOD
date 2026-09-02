"""Phase 13, Part 5-7: overnight/intraday return decomposition features —
a NEW module. Every feature here is derived DIRECTLY from Open/High/Low/
Close, per the phase's explicit requirement that the primary information
source be OHLC decomposition, not a renamed ordinary-momentum feature.

CORE IDENTITY (Part 5, verified on real data in
scripts/phase13_step0_data_quality_gate.py and pinned by
tests/test_overnight_intraday_features.py::test_overnight_intraday_identity_matches_close_to_close):

    (1 + overnight_t) * (1 + intraday_t) - 1  ==  close_to_close_t

  overnight_t   = Open_t / Close_{t-1} - 1
  intraday_t    = Close_t / Open_t - 1
  close_to_close_t = Close_t / Close_{t-1} - 1

Built compositionally on the unmodified Phase 2 RealizedVolatility for
the two "extremeness" ratios (GapExtremeness, IntradayExtremeness), using
the SAME "trailing baseline excludes the current bar" causal convention
RelativeVolume/VolumeZScore/VolatilityZScore already established — see
each class's own docstring for exactly why.
"""

from __future__ import annotations

from typing import Sequence

from src.data.bar import Bar
from src.features.base import Feature, FeatureSpec
from src.features.volatility import RealizedVolatility


class OvernightReturn(Feature):
    """Open_t / Close_{t-1} - 1. None at t=0 (no prior close) or when
    either price is non-positive."""

    def __init__(self):
        self.spec = FeatureSpec(
            name="overnight_return", version="1.0", params={}, required_columns=("open", "close"), lookback=1,
            description="Open_t / Close_{t-1} - 1",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        out: list[float | None] = [None] * len(bars)
        for i in range(1, len(bars)):
            prev_close = bars[i - 1].close
            open_ = bars[i].open
            if prev_close <= 0 or open_ <= 0:
                continue
            out[i] = open_ / prev_close - 1
        return out


class IntradayReturn(Feature):
    """Close_t / Open_t - 1. None when either price is non-positive."""

    def __init__(self):
        self.spec = FeatureSpec(
            name="intraday_return", version="1.0", params={}, required_columns=("open", "close"), lookback=0,
            description="Close_t / Open_t - 1",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        out: list[float | None] = []
        for b in bars:
            out.append(None if b.open <= 0 or b.close <= 0 else b.close / b.open - 1)
        return out


class AbsOvernightReturn(Feature):
    """abs(OvernightReturn) — magnitude, not direction (Part 11's
    directional-predictability vs magnitude/volatility-predictability
    distinction starts here)."""

    def __init__(self):
        self._overnight = OvernightReturn()
        self.spec = FeatureSpec(name="abs_overnight_return", version="1.0", params={}, required_columns=("open", "close"), lookback=1, description="abs(Open_t/Close_{t-1} - 1)")

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        return [None if v is None else abs(v) for v in self._overnight.compute(bars)]


class AbsIntradayReturn(Feature):
    """abs(IntradayReturn)."""

    def __init__(self):
        self._intraday = IntradayReturn()
        self.spec = FeatureSpec(name="abs_intraday_return", version="1.0", params={}, required_columns=("open", "close"), lookback=0, description="abs(Close_t/Open_t - 1)")

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        return [None if v is None else abs(v) for v in self._intraday.compute(bars)]


class OvernightIntradayDisagreement(Feature):
    """1.0 if sign(overnight_t) != sign(intraday_t), else 0.0 — the
    PREREGISTERED definition of "disagreement" (Part 7E): zero is treated
    as its own non-positive, non-negative case, so a disagreement is only
    ever flagged between a STRICTLY positive and a STRICTLY negative leg;
    if either leg is exactly 0.0, this returns 0.0 (no disagreement
    flagged) rather than guessing a sign for a flat leg."""

    def __init__(self):
        self._overnight = OvernightReturn()
        self._intraday = IntradayReturn()
        self.spec = FeatureSpec(
            name="overnight_intraday_disagreement", version="1.0", params={}, required_columns=("open", "close"), lookback=1,
            description="1.0 if sign(overnight_t) != sign(intraday_t) else 0.0 (0.0 counts as neither sign)",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        overnight, intraday = self._overnight.compute(bars), self._intraday.compute(bars)
        out: list[float | None] = []
        for o, i in zip(overnight, intraday):
            if o is None or i is None:
                out.append(None)
            else:
                out.append(1.0 if (o > 0 and i < 0) or (o < 0 and i > 0) else 0.0)
        return out


class GapExtremeness(Feature):
    """overnight_t / trailing_realized_vol, where trailing_realized_vol
    is RealizedVolatility(vol_window) measured through t-1 (LAGGED by one
    bar relative to the engine's own causal convention) — deliberately
    more conservative than "through t inclusive": overnight_t is itself
    PART of what RealizedVolatility(vol_window)[t] would incorporate (bar
    t's own close enters that window), so using vol[t] directly would be
    a subtle same-bar self-reference. Lagging by one bar removes it
    entirely, the same "baseline excludes the current bar" convention
    RelativeVolume/VolumeZScore/VolatilityZScore already use. None when
    volatility is None or exactly 0."""

    def __init__(self, vol_window: int = 20):
        if vol_window < 2:
            raise ValueError("vol_window must be >= 2")
        self.vol_window = vol_window
        self._overnight = OvernightReturn()
        self._vol = RealizedVolatility(vol_window)
        self.spec = FeatureSpec(
            name=f"gap_extremeness_{vol_window}", version="1.0", params={"vol_window": vol_window}, required_columns=("open", "close"),
            lookback=vol_window + 1, description=f"overnight_t / RealizedVolatility({vol_window}) measured through t-1 (lagged)",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        overnight = self._overnight.compute(bars)
        vol = self._vol.compute(bars)
        lagged_vol: list[float | None] = [None] + vol[:-1]  # vol[t] used here is the value already known as of t-1
        out: list[float | None] = []
        for o, v in zip(overnight, lagged_vol):
            out.append(None if o is None or v is None or v == 0 else o / v)
        return out


class IntradayExtremeness(Feature):
    """intraday_t / trailing_realized_vol, lagged by one bar — see
    GapExtremeness's docstring for the identical causal reasoning."""

    def __init__(self, vol_window: int = 20):
        if vol_window < 2:
            raise ValueError("vol_window must be >= 2")
        self.vol_window = vol_window
        self._intraday = IntradayReturn()
        self._vol = RealizedVolatility(vol_window)
        self.spec = FeatureSpec(
            name=f"intraday_extremeness_{vol_window}", version="1.0", params={"vol_window": vol_window}, required_columns=("open", "close"),
            lookback=vol_window + 1, description=f"intraday_t / RealizedVolatility({vol_window}) measured through t-1 (lagged)",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        intraday = self._intraday.compute(bars)
        vol = self._vol.compute(bars)
        lagged_vol: list[float | None] = [None] + vol[:-1]
        out: list[float | None] = []
        for i, v in zip(intraday, lagged_vol):
            out.append(None if i is None or v is None or v == 0 else i / v)
        return out


class OvernightIntradayState(Feature):
    """PREREGISTERED categorical state (Part 7H), frozen before testing:
    0 = (overnight >= 0, intraday >= 0)   "+/+"
    1 = (overnight >= 0, intraday <  0)   "+/-"
    2 = (overnight <  0, intraday >= 0)   "-/+"
    3 = (overnight <  0, intraday <  0)   "-/-"
    A sign of exactly 0.0 is grouped with the POSITIVE bucket (>= 0), a
    fixed, documented convention — never changed after seeing results."""

    LABELS = ("+/+", "+/-", "-/+", "-/-")

    def __init__(self):
        self._overnight = OvernightReturn()
        self._intraday = IntradayReturn()
        self.spec = FeatureSpec(
            name="overnight_intraday_state", version="1.0", params={}, required_columns=("open", "close"), lookback=1,
            description="0=+/+ 1=+/- 2=-/+ 3=-/- (sign(0.0) grouped with positive)",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        overnight, intraday = self._overnight.compute(bars), self._intraday.compute(bars)
        out: list[float | None] = []
        for o, i in zip(overnight, intraday):
            if o is None or i is None:
                out.append(None)
                continue
            o_pos, i_pos = o >= 0, i >= 0
            if o_pos and i_pos:
                out.append(0.0)
            elif o_pos and not i_pos:
                out.append(1.0)
            elif not o_pos and i_pos:
                out.append(2.0)
            else:
                out.append(3.0)
        return out

    @classmethod
    def label_for(cls, code: float | None) -> str | None:
        return None if code is None else cls.LABELS[int(code)]


class OvernightIntradayInteraction(Feature):
    """overnight_t * intraday_t — the interaction term Part 12's
    preregistered regression (future_return ~ overnight + intraday +
    overnight*intraday) needs as its own panel column."""

    def __init__(self):
        self._overnight = OvernightReturn()
        self._intraday = IntradayReturn()
        self.spec = FeatureSpec(
            name="overnight_intraday_interaction", version="1.0", params={}, required_columns=("open", "close"), lookback=1,
            description="overnight_t * intraday_t",
        )

    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        overnight, intraday = self._overnight.compute(bars), self._intraday.compute(bars)
        return [None if o is None or i is None else o * i for o, i in zip(overnight, intraday)]
