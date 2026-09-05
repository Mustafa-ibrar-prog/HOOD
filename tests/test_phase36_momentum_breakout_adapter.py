"""Phase 36, Part 18 — the MomentumBreakoutStrategy production adapter.

Uses the exact same fake MarketDataProvider pattern
`tests/test_orchestrator.py` already establishes for exercising the REAL
`MomentumBreakoutStrategy.scan()` -- this test proves the production
interface CAN wrap it, unmodified, nothing more."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from src.market.data_provider import MarketDataProvider
from src.market.errors import QuoteUnavailableError
from src.market.models import EquityQuote, MarketSnapshot, OptionQuote, UnderlyingSnapshot
from src.options.phase35_frozen_strategy_spec import STRATEGY_ID
from src.production.decision import DecisionType
from src.production.momentum_breakout_adapter import MomentumBreakoutProductionAdapter
from src.production.registry import StrategyStatus, build_default_registry
from tests.conftest import make_bars

NOW = datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc)


def _bullish_underlying(symbol="AAPL") -> UnderlyingSnapshot:
    return UnderlyingSnapshot(
        quote=EquityQuote(symbol=symbol, last_trade_price=230.0, previous_close=225.0, as_of=NOW),
        bars=tuple(make_bars([220.0, 224.0, 228.0, 231.0])),
        rsi=62.0, rsi_prev=58.0, macd_histogram=0.10, macd_histogram_prev=0.05,
        ema_fast=230.5, ema_slow=225.0, vwap=228.0, volume_ratio=1.4,
        higher_highs=True, lower_highs=False, breakout_continuation=True, failed_breakout=False, fetched_at=NOW,
    )


def _liquid_option_snapshot(option_id) -> MarketSnapshot:
    return MarketSnapshot(
        option=OptionQuote(
            instrument_id=option_id, bid_price=1.00, ask_price=1.05, last_trade_price=1.025,
            previous_close=0.90, volume=200, open_interest=500, as_of=NOW,
        ),
        underlying=EquityQuote(symbol="AAPL", last_trade_price=230.0, previous_close=225.0, as_of=NOW),
        option_bars=(), underlying_bars=(), rsi=None, rsi_prev=None, macd_histogram=None,
        macd_histogram_prev=None, ema_fast=None, ema_slow=None, vwap=None, volume_ratio=None, fetched_at=NOW,
    )


class _FakeMarketData(MarketDataProvider):
    def __init__(self, *, underlying_snapshots=None, option_snapshots=None, expirations=None, chain_candidates=None):
        self.underlying_snapshots = underlying_snapshots or {}
        self.option_snapshots = option_snapshots or {}
        self.expirations = expirations or {}
        self.chain_candidates = chain_candidates or {}

    def get_market_snapshot(self, option_id, underlying_symbol, now=None):
        if option_id not in self.option_snapshots:
            raise QuoteUnavailableError(f"no snapshot configured for {option_id}")
        return self.option_snapshots[option_id]

    def get_underlying_snapshot(self, symbol, now=None):
        if symbol not in self.underlying_snapshots:
            raise QuoteUnavailableError(f"no snapshot configured for {symbol}")
        return self.underlying_snapshots[symbol]

    def get_option_expirations(self, underlying_symbol):
        return self.expirations.get(underlying_symbol, [])

    def get_option_chain_candidates(self, underlying_symbol, **filters):
        return self.chain_candidates.get(underlying_symbol, [])


def _fake_snapshot_input():
    """A minimal StrategySnapshot -- the adapter only reads .timestamp
    from it, everything else comes from the injected MarketDataProvider
    (matching the REAL orchestrator's own dependency shape)."""
    from src.production.snapshot import AccountState, RiskStateSnapshot, StrategySnapshot

    return StrategySnapshot(
        timestamp=NOW, account=AccountState(account_number="ACC1", buying_power_usd=1000.0, equity_usd=1000.0, as_of=NOW),
        underlying=_bullish_underlying(), option_chain=(), option_quotes={}, positions=(),
        risk_state=RiskStateSnapshot(trades_opened_today=0, daily_pnl_usd=0.0, last_exit_time=None, last_position_size_usd=None, last_trade_was_loss=False),
        risk_limits=None, settings=None,
    )


def test_adapter_maps_a_real_setup_candidate_into_an_enter_decision():
    expiration = date(2026, 8, 18) + timedelta(days=14)
    market = _FakeMarketData(
        underlying_snapshots={"AAPL": _bullish_underlying()},
        expirations={"AAPL": [expiration]},
        chain_candidates={"AAPL": [{"id": "opt-aapl-1", "strike_price": "230.0000"}]},
        option_snapshots={"opt-aapl-1": _liquid_option_snapshot("opt-aapl-1")},
    )
    adapter = MomentumBreakoutProductionAdapter(market, ["AAPL"])
    decision = adapter.decide(_fake_snapshot_input())

    assert decision.decision == DecisionType.ENTER
    assert decision.strategy_id == STRATEGY_ID
    assert decision.underlying == "AAPL"
    assert decision.option_id == "opt-aapl-1"
    assert decision.side == "long_call"
    assert decision.option_type == "call"
    assert decision.quantity_recommendation == 1


def test_adapter_maps_no_setup_into_no_trade():
    market = _FakeMarketData(underlying_snapshots={"AAPL": UnderlyingSnapshot(
        quote=EquityQuote(symbol="AAPL", last_trade_price=230.0, previous_close=225.0, as_of=NOW),
        bars=(), rsi=50.0, rsi_prev=50.0, macd_histogram=0.0, macd_histogram_prev=0.0, ema_fast=230.0,
        ema_slow=230.0, vwap=230.0, volume_ratio=1.0, higher_highs=False, lower_highs=False,
        breakout_continuation=False, failed_breakout=False, fetched_at=NOW,
    )})
    adapter = MomentumBreakoutProductionAdapter(market, ["AAPL"])
    decision = adapter.decide(_fake_snapshot_input())
    assert decision.decision == DecisionType.NO_TRADE


def test_adapter_does_not_modify_the_real_strategys_logic():
    """The adapter constructs the REAL MomentumBreakoutStrategy with no
    config override -- verified by grepping the adapter's own source for
    the absence of a MomentumBreakoutConfig construction with non-default
    values."""
    import inspect

    from src.production import momentum_breakout_adapter

    source = inspect.getsource(momentum_breakout_adapter)
    assert "MomentumBreakoutConfig(" not in source  # never constructs a customized config


def test_adapter_strategy_remains_not_ready_in_the_default_registry():
    """Part 18: 'must not become production-eligible.'"""
    registry = build_default_registry()
    entry = registry.get(STRATEGY_ID, "1.0")
    assert entry.status == StrategyStatus.NOT_READY
    assert entry not in registry.production_eligible_strategies()


def test_adapter_has_no_live_trade_path():
    """No code anywhere constructs a MomentumBreakoutProductionAdapter and
    feeds it into run_live_decision_cycle with a VALIDATED registry entry
    -- confirmed by grepping src/ (never just tests/) for the adapter's
    class name outside its own defining module."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    hits = []
    for path in (repo_root / "src").rglob("*.py"):
        if path.name == "momentum_breakout_adapter.py":
            continue
        if "MomentumBreakoutProductionAdapter" in path.read_text():
            hits.append(path)
    assert hits == [], f"MomentumBreakoutProductionAdapter is referenced outside its own module: {hits}"
