"""Polymarket 15-minute Bitcoin up/down trading — a separate system that
lives alongside the existing Robinhood/options code (src/strategy,
src/market, src/risk, src/execution, ...), reusing none of its
options-specific models (OptionQuote, OrderLeg.option_id, strikes,
expirations) because a Polymarket binary market is a fundamentally
different instrument: a YES/NO token pair trading between $0 and $1 on a
central limit order book, settled in USDC on Polygon.

What IS reused, deliberately: the safety philosophy, not the code.
- src.execution.emergency_stop.EmergencyStopStore is generic (a
  file-backed boolean) and is imported as-is, pointed at its own file.
- Everything else here (settings, risk, gateway, reconciliation,
  pending-order approval) is a fresh implementation of the same pattern
  this codebase already trusts for real-money safety: TRADING_MODE=paper
  by default, LIVE_TRADING_CONFIRMED as an independent second switch,
  live orders gated on pending-approval unless auto-execute is explicitly
  turned on, and a kill switch checked immediately before every real order.

Two correctness properties specific to this package, beyond the
Robinhood side's own safety gates (see each module's docstring for the
full detail):
- "Placed" is never "filled". gateway.py only ever records a
  SubmissionOutcome; reconciliation.py is the ONLY path from there to
  an OpenPosition, and only ever from a fresh, authoritative FillResult
  lookup — never fabricated from the submission response.
- Order-book liquidity is actually enforced, not just configured:
  risk.py's check_order_book_liquidity() refuses a trade the SPECIFIC
  outcome's own book can't absorb near our ceiling price.

IMPORTANT, read before running for real money:
  1. This was written in an environment whose network egress policy
     blocks polymarket.com outright (confirmed on gamma-api.polymarket.com
     and clob.polymarket.com) — none of the live-API-calling code in
     here has been executed against the real API. Verify independently,
     in an environment with network access, before trusting it with real
     funds: market discovery (client.find_active_btc_market), order
     submission/fill shapes, and the polymarket-client SDK version
     declared as the optional `polymarket` extra in pyproject.toml. See
     client.py's module docstring for the primary-source verification
     already done against that SDK's real source code (not its docs,
     not a summary) — py-clob-client, the SDK an earlier version of this
     package used, is ARCHIVED and no longer functional.
  2. Nothing here has been told your actual risk tolerance. The defaults
     in settings.py (tiny bet size, tiny daily loss cap, tiny minimum
     order-book liquidity) are deliberately conservative placeholders —
     read and set every POLYMARKET_* value in .env.polymarket.example
     yourself before TRADING_MODE=live.
"""
