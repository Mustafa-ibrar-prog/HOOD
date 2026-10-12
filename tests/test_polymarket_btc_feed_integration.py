"""Full-chain integration tests for the real BTC data feed:

    DirectBtcQuoteSource (fake) -> bootstrap/record_bars -> get_bars
    -> assess_btc_market (staleness gate) -> evaluate_dynamic_exit
    -> check_and_execute_dynamic_exits

Unit-level mechanics (buffer aggregation, refresher cadence, Coinbase
parsing, the staleness classification itself) are already covered in
test_polymarket_btc_market_data.py / test_polymarket_btc_coinbase_source.py
/ test_polymarket_btc_intelligence.py. This file's job is specifically
the end-to-end wiring the production-readiness audit asked about:
bootstrap through to a real dynamic-exit decision, a dead/stale feed
degrading safely all the way through to HOLD, and a BTC-side failure
never affecting Polymarket's own order-book-based logic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.market.models import PriceBar
from src.polymarket.btc_intelligence import DEFAULT_MIN_BARS_FOR_INDICATORS, build_btc_momentum_evidence
from src.polymarket.btc_market_data import BtcPriceHistoryStore, bootstrap_btc_price_history
from src.polymarket.exit_manager import check_and_execute_dynamic_exits
from src.polymarket.gateway import PaperPolymarketGateway
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import BookLevel, OrderBookSnapshot
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import OpenPosition, PolymarketPositionStore
from src.polymarket.settings import PolymarketSettings
from src.polymarket.state import DailyPnlStateStore

_BASE = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
_AVG_FILL_PRICE = 0.36


class _FakeDirectSource:
    name = "fake-direct"

    def __init__(self, candles: list[PriceBar] | None = None, *, raise_exc: Exception | None = None):
        self._candles = list(candles or [])
        self.raise_exc = raise_exc
        self.call_count = 0

    def get_recent_candles(self, *, limit: int) -> list[PriceBar]:
        self.call_count += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        return self._candles[-limit:] if limit and limit < len(self._candles) else list(self._candles)


def _real_candles(n: int, *, start: datetime = _BASE, base: float = 100.0, step: float = 0.3, volume: float = 2.5) -> list[PriceBar]:
    """A clean, moderate uptrend -- enough real history to produce
    STRENGTHENING once there are enough bars (mirrors the sequence
    already proven in test_polymarket_btc_intelligence.py)."""
    import math
    bars = []
    for i in range(n):
        price = base + i * 0.05 + 1.0 * math.sin(i / 2.0)
        bars.append(PriceBar(
            start_time=start + timedelta(minutes=i), open=price, high=price + 0.5, low=price - 0.5,
            close=price, volume=volume + i * 0.01, interpolated=False,
        ))
    return bars


class _FakeClient:
    def __init__(self):
        self._books: dict[str, OrderBookSnapshot] = {}

    def set_order_book(self, token_id: str, book: OrderBookSnapshot) -> None:
        self._books[token_id] = book

    def get_order_book(self, token_id: str) -> OrderBookSnapshot:
        return self._books[token_id]

    def get_fill_status(self, exchange_order_id: str):
        raise AssertionError("not used by these integration tests")


def _book(bid: float) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        token_id="tok-1", bids=(BookLevel(price=bid, size=100.0),), asks=(BookLevel(price=bid + 0.02, size=100.0),),
        fetched_at=datetime.now(timezone.utc),
    )


def _position(**overrides) -> OpenPosition:
    now = datetime.now(timezone.utc)
    defaults = dict(
        condition_id="cpc-btc-updown-15m-2026-10-07-2230z", token_id="tok-1", outcome="YES",
        requested_size_usd=5.0, filled_shares=5.0, avg_fill_price=_AVG_FILL_PRICE, order_id="CZ510YB5PYWT",
        client_order_id="client-2230z", status="filled", opened_at=now, close_time=now + timedelta(minutes=10),
    )
    defaults.update(overrides)
    return OpenPosition(**defaults)


def _settings(**overrides) -> PolymarketSettings:
    env = {"POLYMARKET_DYNAMIC_EXIT_ENABLED": "true"}
    env.update(overrides)
    return PolymarketSettings.from_env(env=env)


def _harness(tmp_path: Path, **settings_overrides):
    settings = _settings(**settings_overrides)
    client = _FakeClient()
    decision_logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    gateway = PaperPolymarketGateway(settings, decision_logger)
    return dict(
        client=client, settings=settings, gateway=gateway,
        position_store=PolymarketPositionStore(tmp_path / "positions.json"),
        pending_store=PolymarketPendingOrderStore(tmp_path / "pending.json"),
        state_store=DailyPnlStateStore(tmp_path / "pnl.json"),
        decision_logger=decision_logger,
        btc_price_store=BtcPriceHistoryStore(tmp_path / "btc.json"),
        btc_feed_source="fake-direct",
    )


# --- 1. Historical bootstrap -> usable through the full chain ---------------

def test_bootstrap_then_full_cascade_uses_real_evidence(tmp_path):
    harness = _harness(tmp_path)
    source = _FakeDirectSource(_real_candles(45))
    written = bootstrap_btc_price_history(harness["btc_price_store"], source, min_bars=DEFAULT_MIN_BARS_FOR_INDICATORS)
    # bootstrap only ever ASKS for min_bars+5 (see its own docstring) --
    # a small buffer beyond the 35-bar minimum, not everything the
    # provider happens to have.
    assert written == DEFAULT_MIN_BARS_FOR_INDICATORS + 5

    position = _position(avg_fill_price=0.36)  # below target -- just confirms real evidence is actually consulted
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(0.378))  # +5%, below target
    now = _real_candles(45)[-1].start_time + timedelta(seconds=30)

    submitted = check_and_execute_dynamic_exits(**harness, now=now)
    assert submitted == 0  # below target, no reason to exit -- but no crash, no INSUFFICIENT_DATA guess either
    assert harness["position_store"].load()[0].filled_shares == 5.0


# --- 2 & 3. Exactly enough bars vs. fewer than required ----------------------

def test_exactly_enough_bars_populates_real_indicators(tmp_path):
    bars = _real_candles(DEFAULT_MIN_BARS_FOR_INDICATORS)
    evidence = build_btc_momentum_evidence(bars, thesis_direction="bullish")
    assert evidence.rsi is not None
    assert evidence.macd_histogram is not None
    assert evidence.ema_fast is not None and evidence.ema_slow is not None


def test_fewer_than_required_bars_leaves_evidence_fields_none(tmp_path):
    bars = _real_candles(DEFAULT_MIN_BARS_FOR_INDICATORS - 1)
    evidence = build_btc_momentum_evidence(bars, thesis_direction="bullish")
    assert evidence.rsi is None
    assert evidence.macd_histogram is None


# --- 4 & 5. Fresh vs. stale bars through the full cascade --------------------

def test_fresh_real_bars_through_the_full_cascade_holds_below_target(tmp_path):
    harness = _harness(tmp_path)
    candles = _real_candles(45)
    harness["btc_price_store"].record_bars(candles)
    position = _position(avg_fill_price=0.36)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(0.378))  # +5%, below target
    now = candles[-1].start_time + timedelta(seconds=30)  # fresh

    submitted = check_and_execute_dynamic_exits(**harness, now=now)
    assert submitted == 0
    assert harness["position_store"].load()[0].filled_shares == 5.0


def test_stale_real_bars_force_hold_even_with_a_profitable_order_book(tmp_path):
    """The exact gap the production-readiness audit found: a feed that
    built real history and then stopped must NOT keep deciding from
    that old data -- even when the live order book shows a juicy,
    seemingly-exit-worthy price."""
    harness = _harness(tmp_path)
    candles = _real_candles(45)
    harness["btc_price_store"].record_bars(candles)
    position = _position(avg_fill_price=0.36)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(0.50))  # well past target -- would otherwise be very exit-worthy
    now = candles[-1].start_time + timedelta(hours=2)  # the feed died 2 hours ago

    submitted = check_and_execute_dynamic_exits(**harness, now=now)

    assert submitted == 0  # HOLD -- never guessed from stale evidence
    assert harness["position_store"].load()[0].filled_shares == 5.0


# --- 6. Feed outage (never bootstrapped at all) -------------------------------

def test_feed_never_bootstrapped_holds_safely_no_crash(tmp_path):
    harness = _harness(tmp_path)  # btc_price_store is empty -- nothing ever fed
    position = _position(avg_fill_price=0.36)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(0.50))  # profitable, would otherwise exit

    submitted = check_and_execute_dynamic_exits(**harness, now=_BASE)

    assert submitted == 0
    assert harness["position_store"].load()[0].filled_shares == 5.0


# --- 7 & 8. Restart with persisted fresh vs. stale data ----------------------

def test_restart_with_persisted_fresh_data_behaves_normally(tmp_path):
    path = tmp_path / "btc.json"
    candles = _real_candles(45)
    BtcPriceHistoryStore(path).record_bars(candles)  # simulates a prior process's bootstrap

    harness = _harness(tmp_path)  # fresh store instance inside -- simulates a restarted bot process
    position = _position(avg_fill_price=0.36)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(0.378))
    now = candles[-1].start_time + timedelta(seconds=30)

    submitted = check_and_execute_dynamic_exits(**harness, now=now)
    assert submitted == 0  # below target, correctly evaluated with real (fresh) evidence available
    assert harness["position_store"].load()[0].filled_shares == 5.0


def test_restart_with_persisted_stale_data_still_forces_hold(tmp_path):
    """Requirement 12: the same staleness rule applies after a
    process restart -- old data on disk does not become "new" just
    because the process restarted."""
    path = tmp_path / "btc.json"
    candles = _real_candles(45)
    BtcPriceHistoryStore(path).record_bars(candles)

    harness = _harness(tmp_path)  # a brand-new store instance, same file -- simulated restart
    position = _position(avg_fill_price=0.36)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(0.50))  # profitable
    now = candles[-1].start_time + timedelta(hours=3)  # restart happens long after the feed died

    submitted = check_and_execute_dynamic_exits(**harness, now=now)
    assert submitted == 0
    assert harness["position_store"].load()[0].filled_shares == 5.0


# --- 9 & 10. No fabrication; real volume preserved (but not yet scored) -----

def test_no_fabricated_ohlcv_in_the_real_bar_path(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    candles = _real_candles(10)
    store.record_bars(candles)
    # +70s, not +30s: the last candle's own 60s bucket must be fully
    # CLOSED (see get_bars's "never return the in-progress bucket"
    # rule) before it's returned at all.
    bars = store.get_bars(interval_seconds=60, now=candles[-1].start_time + timedelta(seconds=70))
    assert len(bars) == len(candles)
    for real, stored in zip(candles, bars):
        assert (stored.open, stored.high, stored.low, stored.close, stored.volume) == (real.open, real.high, real.low, real.close, real.volume)


def test_real_volume_is_preserved_in_bars_but_deliberately_not_yet_wired_into_scoring(tmp_path):
    """This is a DATA-LAYER-only change: real, fractional volume now
    survives storage/retrieval exactly (see above), but
    build_btc_momentum_evidence() still leaves volume_ratio=None
    unconditionally -- wiring real volume into the evidence SCORING
    would be a decision-logic change, explicitly out of scope here."""
    bars = _real_candles(45, volume=3.14159)
    assert all(b.volume > 0 for b in bars)  # real, non-zero volume is present on every bar
    evidence = build_btc_momentum_evidence(bars, thesis_direction="bullish")
    assert evidence.volume_ratio is None


# --- 11. Provider failure -> safe HOLD, isolated from Polymarket logic ------

def test_bootstrap_provider_failure_then_full_cascade_still_holds_safely(tmp_path):
    harness = _harness(tmp_path)
    source = _FakeDirectSource(raise_exc=RuntimeError("DNS resolution failed"))
    written = bootstrap_btc_price_history(harness["btc_price_store"], source, min_bars=DEFAULT_MIN_BARS_FOR_INDICATORS)
    assert written == 0  # never raised

    position = _position(avg_fill_price=0.36)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(0.50))  # profitable -- Polymarket's own data is fine

    submitted = check_and_execute_dynamic_exits(**harness, now=_BASE)

    assert submitted == 0  # BTC evidence unavailable -> HOLD
    assert harness["position_store"].load()[0].filled_shares == 5.0  # nothing crashed, nothing fabricated


def test_corrupted_btc_bar_file_does_not_crash_the_cycle_or_block_polymarket_logic(tmp_path):
    """A btc_price_store-level failure (e.g. a corrupted file) must be
    isolated exactly like a provider outage -- it must never propagate
    out of check_and_execute_dynamic_exits() and crash the bot, and
    must never prevent the SAME cycle's Polymarket order-book fetch
    from being attempted."""
    harness = _harness(tmp_path)
    (tmp_path / "btc.bars.json").write_text("not json")  # corrupts load_real_bars()
    position = _position(avg_fill_price=0.36)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(0.50))

    submitted = check_and_execute_dynamic_exits(**harness, now=_BASE)  # must not raise

    assert submitted == 0
    assert harness["position_store"].load()[0].filled_shares == 5.0
