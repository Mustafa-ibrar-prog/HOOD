"""Polymarket 15-minute Bitcoin up/down trading — a separate system that
lives alongside the existing Robinhood/options code (src/strategy,
src/market, src/risk, src/execution, ...), reusing none of its
options-specific models (OptionQuote, OrderLeg.option_id, strikes,
expirations) because a Polymarket binary market is a fundamentally
different instrument: a YES/NO proposition trading between $0 and $1,
not a strike/expiration option contract.

TWO VENUES, selected by settings.py's POLYMARKET_VENUE (verified by
installing BOTH official SDKs directly and inspecting their real
source/types — see client.py's and us_client.py's module docstrings):
international polymarket.com (ERC-1155 YES/NO token pair, its own order
book each, settled in USDC on Polygon, EVM-private-key order signing —
client.py, `polymarket-client`) and Polymarket US (traded via QCX LLC,
a CFTC-regulated exchange; ONE contract per market, YES/NO expressed as
BUY_LONG/BUY_SHORT on that same contract, USD cash balance, Ed25519
key_id+secret_key auth with NO wallet/private-key concept at all —
us_client.py, `polymarket-us`). These are genuinely different systems,
not regional variants of one CLOB — client.py's
get_polymarket_client(settings) is the one factory every script uses
to get whichever one POLYMARKET_VENUE selects; everything downstream
(engine.py, gateway.py, reconciliation.py, risk.py, strategy.py,
positions.py) is written against their shared method surface and never
needs to know or care which venue it's actually talking to.

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
     blocks BOTH venues outright — confirmed directly via curl on
     gamma-api.polymarket.com, clob.polymarket.com, api.polymarket.us,
     and gateway.polymarket.us (all refused at the CONNECT-tunnel stage
     by the sandbox's own proxy, not by Polymarket) — so none of the
     live-API-calling code in client.py or us_client.py has been
     executed against either real API. Verify independently, in an
     environment with network access, before trusting it with real
     funds: market discovery (client.find_active_btc_market /
     us_client.PolymarketUSClient.find_active_btc_market), order
     submission/fill shapes, and whichever SDK POLYMARKET_VENUE selects
     (declared as the optional `polymarket` extra in pyproject.toml).
     See client.py's and us_client.py's module docstrings for the
     primary-source verification already done against each SDK's real,
     installed source code (not its docs, not a summary) — py-clob-client,
     the SDK an earlier version of the international path used, is
     ARCHIVED and no longer functional; Polymarket US's BTC-15-minute
     market existence and its "bet NO" (BUY_SHORT) pricing mechanics are
     the two most important things to confirm live before that venue is
     trusted — see us_client.py's module docstring.
  2. Nothing here has been told your actual risk tolerance. The defaults
     in settings.py (tiny bet size, tiny daily loss cap, tiny minimum
     order-book liquidity) are deliberately conservative placeholders —
     read and set every POLYMARKET_* value in .env.polymarket.example
     yourself before TRADING_MODE=live.
"""
