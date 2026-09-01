"""Modular feature-engineering framework for the research/quant platform.

Categories implemented (deliberately a small, representative set per
category rather than "hundreds of indicators" — see each module's own
docstring):
  price.py          simple/log/cumulative/rolling returns
  momentum.py        momentum, rate of change, moving average, MA distance
  volatility.py       rolling std, realized volatility, ATR, vol percentile
  volume.py           rolling volume, volume change, relative volume, volume percentile
  mean_reversion.py   rolling z-score, distance from MA, standardized returns
  relationship.py     rolling correlation, rolling beta, relative strength (pairwise)
  regime.py           trend regime, volatility regime, momentum regime

Every feature is causal by construction — see base.py's module docstring
for the no-future-data contract and how it's tested.
"""

from __future__ import annotations

from src.features.base import Feature, FeatureSpec
from src.features.engine import FeatureEngine, FeatureFrame

__all__ = ["Feature", "FeatureSpec", "FeatureEngine", "FeatureFrame"]
