"""Small fixed constants shared across modules.

Tunable *numbers* (limits, thresholds) belong in settings.py, sourced from
the environment. This file only holds things that are not meant to be
configured per-deployment.
"""

from __future__ import annotations

# Default market timezone used when a Settings instance doesn't override it.
DEFAULT_MARKET_TIMEZONE = "America/New_York"

# Standard US equity/options contract multiplier (1 contract = 100 shares).
CONTRACT_MULTIPLIER = 100

# Python's date.weekday(): Monday=0 ... Sunday=6.
TRADING_WEEKDAYS = frozenset({0, 1, 2, 3, 4})

# Allowed values for TRADING_MODE.
TRADING_MODE_PAPER = "paper"
TRADING_MODE_LIVE = "live"
VALID_TRADING_MODES = frozenset({TRADING_MODE_PAPER, TRADING_MODE_LIVE})
