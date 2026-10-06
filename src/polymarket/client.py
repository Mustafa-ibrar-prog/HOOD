"""Real network client for Polymarket — the only module that may ever
call out to clob.polymarket.com or gamma-api.polymarket.com. Two
sub-concerns, two libraries:

  - Order book, pricing, and order placement/signing: py-clob-client
    (the official SDK) via self._clob. Hand-rolling EIP-712 order
    signing for real money is exactly the kind of mistake a maintained
    SDK exists to prevent — this wrapper never reimplements signing.
  - Market discovery (which condition_id is the current 15-min BTC
    market): the public Gamma API via plain `requests` calls, parsed
    defensively (missing/unexpected fields -> None, never guessed) —
    same posture src/market/hood_provider.py takes toward HOOD tool
    responses.

NOT independently verified against the real API: this entire module
was written in a network-sandboxed environment that cannot reach
polymarket.com (see src/polymarket/__init__.py). Before trusting this
with real funds, run scripts/verify_polymarket_setup.py (read-only: logs
in, fetches markets, prints what it found) somewhere with network
access and confirm find_active_btc_market() actually finds a real,
currently-open 15-minute BTC market — the exact Gamma API query
(tag/slug pattern) below is a best-effort guess, not a confirmed fact.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.polymarket.models import BinaryMarket, OrderRequest
from src.polymarket.settings import PolymarketSettings

_REQUEST_TIMEOUT_SECONDS = 10


def _requests():
    """Lazy import so this module — and anything that only needs its
    exception types or pure-logic pieces, like tests — can be imported
    without the `requests` package installed. Every method that talks
    to the network calls this instead of importing at module level."""
    try:
        import requests
    except ImportError as exc:
        raise PolymarketClientError(
            "The `requests` package is not installed — run `pip install requests` "
            "(see pyproject.toml). Only needed for actual network calls."
        ) from exc
    return requests


class PolymarketClientError(RuntimeError):
    pass


class NoActiveMarketError(PolymarketClientError):
    """Raised by find_active_btc_market() when no market matching the
    configured asset/duration is currently open. Callers must treat this
    as "sit this cycle out," never silently fall back to a different
    market than the one actually configured."""


class PolymarketClient:
    def __init__(self, settings: PolymarketSettings):
        self._settings = settings
        self._clob = None  # lazy — see _clob_client(); paper-mode callers may never need it

    # --- py-clob-client, lazily constructed so paper-mode / discovery-only
    # callers never need credentials or the dependency installed --------------
    def _clob_client(self):
        if self._clob is not None:
            return self._clob
        try:
            from py_clob_client.client import ClobClient
        except ImportError as exc:
            raise PolymarketClientError(
                "py-clob-client is not installed — run `pip install py-clob-client` "
                "(see pyproject.toml). Only needed for order placement / authenticated "
                "calls; market discovery alone (find_active_btc_market) doesn't need it."
            ) from exc

        if self._settings.api_key and self._settings.api_secret and self._settings.api_passphrase:
            from py_clob_client.clob_types import ApiCreds
            client = ClobClient(
                self._settings.clob_api_url, key=self._settings.private_key,
                chain_id=self._settings.chain_id, funder=self._settings.funder_address,
            )
            client.set_api_creds(ApiCreds(
                api_key=self._settings.api_key, api_secret=self._settings.api_secret,
                api_passphrase=self._settings.api_passphrase,
            ))
        elif self._settings.private_key:
            client = ClobClient(
                self._settings.clob_api_url, key=self._settings.private_key,
                chain_id=self._settings.chain_id, funder=self._settings.funder_address,
            )
            client.set_api_creds(client.create_or_derive_api_creds())
        else:
            raise PolymarketClientError(
                "No Polymarket credentials configured — set either "
                "POLYMARKET_PRIVATE_KEY, or POLYMARKET_API_KEY/_SECRET/_PASSPHRASE "
                "plus POLYMARKET_FUNDER_ADDRESS. See .env.polymarket.example."
            )
        self._clob = client
        return client

    # --- Market discovery (Gamma API, no credentials needed) -----------------
    def find_active_btc_market(self, *, now: datetime | None = None) -> BinaryMarket:
        """Finds the currently-open market for settings.asset whose
        duration is closest to settings.market_duration_minutes.

        UNVERIFIED (see module docstring): the tag/slug filter below is a
        best-effort guess at how Polymarket's crypto up/down markets are
        tagged on the Gamma API, not a confirmed fact. If this starts
        raising NoActiveMarketError in a real run, the first thing to
        check is this query against https://gamma-api.polymarket.com's
        actual, current response shape — not this code's logic.
        """
        now = now or datetime.now(timezone.utc)
        resp = _requests().get(
            f"{self._settings.gamma_api_url}/events",
            params={"active": "true", "closed": "false", "tag": self._settings.asset, "limit": 50},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        events = resp.json()
        if not isinstance(events, list):
            raise PolymarketClientError(f"Unexpected /events response shape: {type(events).__name__}")

        target_seconds = self._settings.market_duration_minutes * 60
        best: dict[str, Any] | None = None
        best_diff: float | None = None
        for event in events:
            for market in event.get("markets") or []:
                parsed = _try_parse_duration(market, now=now)
                if parsed is None:
                    continue
                diff = abs(parsed - target_seconds)
                if best_diff is None or diff < best_diff:
                    best, best_diff = market, diff

        if best is None:
            raise NoActiveMarketError(
                f"No open {self._settings.asset} market found near "
                f"{self._settings.market_duration_minutes} minutes in duration right now."
            )
        return self._parse_market(best, now=now)

    def _parse_market(self, raw: dict[str, Any], *, now: datetime) -> BinaryMarket:
        token_ids = raw.get("clobTokenIds")
        if isinstance(token_ids, str):
            import json
            token_ids = json.loads(token_ids)
        if not isinstance(token_ids, list) or len(token_ids) != 2:
            raise PolymarketClientError(f"Market {raw.get('conditionId')!r} does not have exactly 2 outcome tokens")

        condition_id = raw.get("conditionId")
        close_raw = raw.get("endDate") or raw.get("end_date_iso")
        if not condition_id or not close_raw:
            raise PolymarketClientError(f"Market response missing conditionId/endDate: {raw!r}")
        close_time = datetime.fromisoformat(close_raw.replace("Z", "+00:00"))

        yes_bid = yes_ask = None
        try:
            book = self.get_order_book(token_ids[0])
            yes_bid, yes_ask = book
        except Exception:  # noqa: BLE001 - price is optional at parse time; callers that need it call get_order_book themselves
            pass

        return BinaryMarket(
            condition_id=condition_id, question=raw.get("question", ""),
            token_id_yes=token_ids[0], token_id_no=token_ids[1],
            close_time=close_time, fetched_at=now, yes_bid=yes_bid, yes_ask=yes_ask,
        )

    def get_order_book(self, token_id: str) -> tuple[float | None, float | None]:
        """Returns (best_bid, best_ask) for one outcome token, in dollars.
        Uses the CLOB API's public order-book endpoint directly (no
        credentials needed — this is public market data)."""
        resp = _requests().get(
            f"{self._settings.clob_api_url}/book", params={"token_id": token_id}, timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        book = resp.json()
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        best_bid = max((float(b["price"]) for b in bids), default=None)
        best_ask = min((float(a["price"]) for a in asks), default=None)
        return best_bid, best_ask

    def refresh(self, market: BinaryMarket) -> BinaryMarket:
        """Re-fetches just the order book for an already-known market —
        far cheaper than find_active_btc_market() for a strategy that's
        polling the same market every poll_interval_seconds."""
        yes_bid, yes_ask = self.get_order_book(market.token_id_yes)
        from dataclasses import replace
        return replace(market, yes_bid=yes_bid, yes_ask=yes_ask, fetched_at=datetime.now(timezone.utc))

    # --- Order placement (implements gateway.py's PolymarketOrderPlacer) -----
    def place_order(self, order: OrderRequest) -> dict[str, Any]:
        from py_clob_client.clob_types import OrderArgs
        from py_clob_client.order_builder.constants import BUY, SELL

        client = self._clob_client()
        side = BUY if order.side == "BUY" else SELL
        shares = order.size_usd / order.price
        order_args = OrderArgs(price=order.price, size=shares, side=side, token_id=order.token_id)
        signed_order = client.create_order(order_args)
        return client.post_order(signed_order)

    def get_resolution(self, condition_id: str) -> str | None:
        """Returns "YES"/"NO" if this market has resolved, else None.
        UNVERIFIED (see module docstring) — the exact field Gamma uses
        for the winning outcome on a closed market has not been
        confirmed against a live response from this environment."""
        resp = _requests().get(f"{self._settings.gamma_api_url}/markets", params={"condition_ids": condition_id}, timeout=_REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return None
        row = rows[0]
        if not row.get("closed"):
            return None
        outcome = row.get("winningOutcome") or row.get("outcome")
        if outcome is None:
            return None
        return "YES" if str(outcome).strip().upper() in {"YES", "1"} else "NO"

    def get_balance_usdc(self) -> float:
        """Best-effort USDC collateral balance check before sizing a
        real bet — py-clob-client's balance-allowance endpoint. Callers
        must not assume this succeeds; a risk check that needs a hard
        balance guarantee should treat an exception here as "unknown,
        don't trade," not "assume funded."""
        client = self._clob_client()
        resp = client.get_balance_allowance()
        return float(resp.get("balance", 0)) / 1_000_000  # USDC has 6 decimals


def _try_parse_duration(market: dict[str, Any], *, now: datetime) -> float | None:
    """Returns the market's duration in seconds if it has both a start
    and end time and is currently open, else None. Defensive: Gamma API
    field names for start time are inconsistent across market types
    (startDate vs createdAt), so this tries both rather than assuming."""
    end_raw = market.get("endDate") or market.get("end_date_iso")
    start_raw = market.get("startDate") or market.get("createdAt")
    if not end_raw or not start_raw:
        return None
    try:
        end = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
        start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if end <= now:
        return None  # already closed
    return (end - start).total_seconds()
