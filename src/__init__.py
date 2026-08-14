"""HOOD options trading system — paper/dry-run foundation.

This package is currently a software foundation only: configuration,
market-data models, a strategy/scanning framework, a position-management
framework, a risk-management framework, an execution layer that is
hard-restricted to simulated (paper) orders, and structured decision
logging.

Nothing in this package places, modifies, or cancels a real order. See
src/execution/gateway.py for the enforcement point.
"""

from __future__ import annotations

__all__: list[str] = []
