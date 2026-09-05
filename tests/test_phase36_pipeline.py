"""Phase 36, Part 14-17 — the live decision pipeline: fail-closed
behavior when no validated strategy exists (the real, current state of
this project), and the full positive path exercised with a SYNTHETIC,
explicitly-test-only fake strategy (never MomentumBreakoutStrategy,
never claimed real or validated) to prove the plumbing works end to end.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest

from src.backtesting.sizing import FixedQuantitySizer
from src.execution.emergency_stop import EmergencyStopStore
from src.execution.system_state import SystemState, SystemStateAuditLog, record_code_transition, record_human_authorized_transition
from src.market.models import EquityQuote, UnderlyingSnapshot
from src.production import failure_modes as fm
from src.production.decision import DecisionType, StrategyDecision
from src.production.live_snapshot import build_live_market_snapshot
from src.production.pipeline import run_live_decision_cycle
from src.production.registry import StrategyMetadata, StrategyRegistry, StrategyStatus, build_default_registry
from src.production.snapshot import AccountState, RiskStateSnapshot, StrategySnapshot
from src.production.strategy_interface import ProductionStrategy
from src.risk.manager import RiskManager
from src.risk.models import RiskLimits
from src.market.models import OptionQuote


def _now():
    return datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc)


def _limits(**overrides) -> RiskLimits:
    defaults = dict(
        max_trades_per_day=4, max_daily_loss_usd=200.0, max_position_size_usd=250.0,
        cooldown_minutes_after_exit=15, stale_data_max_seconds=90.0, max_spread_pct=0.10,
        min_option_volume=50, min_option_open_interest=100, max_extended_move_pct=0.25,
        entry_cutoff_time=time(15, 30),
    )
    defaults.update(overrides)
    return RiskLimits(**defaults)


def _underlying_snapshot() -> UnderlyingSnapshot:
    quote = EquityQuote(symbol="AAPL", last_trade_price=230.0, previous_close=228.0, as_of=_now())
    return UnderlyingSnapshot(
        quote=quote, bars=(), rsi=60.0, rsi_prev=55.0, macd_histogram=0.05, macd_histogram_prev=0.03,
        ema_fast=230.5, ema_slow=229.0, vwap=229.8, volume_ratio=1.3, higher_highs=True, lower_highs=False,
        breakout_continuation=True, failed_breakout=False, fetched_at=_now(),
    )


def _snapshot(*, account_number="ACC1", buying_power=1000.0) -> StrategySnapshot:
    equity = EquityQuote(symbol="AAPL", last_trade_price=230.0, previous_close=228.0, as_of=_now())
    option_quote = OptionQuote(
        instrument_id="opt-1", bid_price=1.0, ask_price=1.05, last_trade_price=1.02,
        previous_close=0.9, volume=100, open_interest=200, as_of=_now(),
    )
    live = build_live_market_snapshot(
        equity_quote=equity, option_quote=option_quote, underlying_symbol="AAPL", option_id="opt-1",
        option_type="call", strike=230.0, expiration=date(2026, 10, 1), dte_days=26, state="active", tradability="tradable",
    )
    return StrategySnapshot(
        timestamp=_now(),
        account=AccountState(account_number=account_number, buying_power_usd=buying_power, equity_usd=buying_power, as_of=_now()),
        underlying=_underlying_snapshot(),
        option_chain=(),
        option_quotes={"opt-1": live},
        positions=(),
        risk_state=RiskStateSnapshot(trades_opened_today=0, daily_pnl_usd=0.0, last_exit_time=None, last_position_size_usd=None, last_trade_was_loss=False),
        risk_limits=_limits(),
        settings=None,  # not read anywhere in this test's path
    )


class _FakeEnterStrategy(ProductionStrategy):
    """A SYNTHETIC, test-only strategy -- never claimed real or
    validated outside this test file. Exists purely to exercise the
    pipeline's positive path, which no real strategy in this project
    can currently reach (Phase 35: MomentumBreakoutStrategy is
    NOT_READY)."""

    strategy_id = "TEST-FAKE-STRATEGY"

    def decide(self, snapshot: StrategySnapshot) -> StrategyDecision:
        return StrategyDecision(
            strategy_id=self.strategy_id, timestamp=snapshot.timestamp, decision=DecisionType.ENTER,
            underlying="AAPL", option_id="opt-1", side="long_call", quantity_recommendation=1, signal_score=0.9,
        )


class _FakeNoTradeStrategy(ProductionStrategy):
    strategy_id = "TEST-FAKE-STRATEGY"

    def decide(self, snapshot: StrategySnapshot) -> StrategyDecision:
        return StrategyDecision(strategy_id=self.strategy_id, timestamp=snapshot.timestamp, decision=DecisionType.NO_TRADE)


def _validated_registry() -> StrategyRegistry:
    from src.production.validation_artifact import ValidationArtifact, ValidationArtifactStore

    store = ValidationArtifactStore.__new__(ValidationArtifactStore)
    store._path = None  # not used -- we register status directly below, bypassing file I/O for this in-memory test
    registry = StrategyRegistry()
    registry.register(StrategyMetadata(
        strategy_id="TEST-FAKE-STRATEGY", version="1.0", status=StrategyStatus.VALIDATED, created_at=_now(),
        validation_status="TEST FIXTURE ONLY -- never a real validation", historical_evidence_status="n/a",
        live_data_compatibility_status="n/a", allowed_option_structures=("long_call",),
        parameter_specification="test fixture", risk_profile="test fixture", author_or_research_provenance="test fixture",
    ))
    return registry


def _authorized_stores(tmp_path):
    stop_store = EmergencyStopStore(tmp_path / "stop.json")
    stop_store.clear(authorized_by="user:test", reason="test fixture")
    audit_log = SystemStateAuditLog(tmp_path / "audit.jsonl")
    audit_log.append_transition(record_code_transition(SystemState.RESEARCH, SystemState.VALIDATED_STRATEGY, reason="x"))
    audit_log.append_transition(record_human_authorized_transition(SystemState.VALIDATED_STRATEGY, SystemState.HUMAN_LIVE_AUTHORIZATION, authorized_by="user:test", reason="x"))
    audit_log.append_transition(record_human_authorized_transition(SystemState.HUMAN_LIVE_AUTHORIZATION, SystemState.LIVE_AUTONOMOUS_TRADING, authorized_by="user:test", reason="x"))
    return stop_store, audit_log


# --- Part 14: no-strategy fail-closed, using the REAL default registry -----------------------


def test_default_registry_produces_no_validated_strategy():
    """This is the REAL, current state of the project -- MomentumBreakoutStrategy
    is NOT_READY, and no other strategy is registered. The pipeline must
    refuse before calling any strategy at all."""
    result = run_live_decision_cycle(
        registry=build_default_registry(), strategies_by_id={}, snapshots_by_underlying={"AAPL": _snapshot()},
        risk_manager=RiskManager(_limits()), sizer=FixedQuantitySizer(1), account_number="ACC1", now=_now(),
    )
    assert result.decision_type == DecisionType.NO_TRADE
    assert result.outcome_code == fm.NO_VALIDATED_STRATEGY


def test_no_strategy_fail_closed_regardless_of_risk_or_account_state():
    """Part 14: must be NO_TRADE/NO_VALIDATED_STRATEGY regardless of risk
    configuration, account balance, or market conditions -- pass in an
    absurdly permissive risk config and a healthy account; still blocked
    first."""
    generous_limits = _limits(max_trades_per_day=1000, max_position_size_usd=1_000_000.0)
    result = run_live_decision_cycle(
        registry=build_default_registry(), strategies_by_id={}, snapshots_by_underlying={"AAPL": _snapshot(buying_power=1_000_000.0)},
        risk_manager=RiskManager(generous_limits), sizer=FixedQuantitySizer(100), account_number="ACC1", now=_now(),
    )
    assert result.outcome_code == fm.NO_VALIDATED_STRATEGY


def test_registered_but_not_read_strategy_never_gets_called():
    """A strategy present in `strategies_by_id` but NOT production-eligible
    in the registry must never even have `decide()` invoked."""
    calls = []

    class _Spy(ProductionStrategy):
        strategy_id = "MOMENTUM_BREAKOUT_EXISTING_V1"

        def decide(self, snapshot):
            calls.append(1)
            return StrategyDecision(strategy_id=self.strategy_id, timestamp=snapshot.timestamp, decision=DecisionType.NO_TRADE)

    result = run_live_decision_cycle(
        registry=build_default_registry(), strategies_by_id={"MOMENTUM_BREAKOUT_EXISTING_V1": _Spy()},
        snapshots_by_underlying={"AAPL": _snapshot()}, risk_manager=RiskManager(_limits()), sizer=FixedQuantitySizer(1),
        account_number="ACC1", now=_now(),
    )
    assert result.outcome_code == fm.NO_VALIDATED_STRATEGY
    assert calls == []


# --- Account unavailable -----------------------------------------------------------------------


def test_account_unavailable_blocks_before_any_strategy_runs():
    snap = _snapshot(account_number=None, buying_power=None)
    result = run_live_decision_cycle(
        registry=_validated_registry(), strategies_by_id={"TEST-FAKE-STRATEGY": _FakeEnterStrategy()},
        snapshots_by_underlying={"AAPL": snap}, risk_manager=RiskManager(_limits()), sizer=FixedQuantitySizer(1),
        account_number="ACC1", now=_now(),
    )
    assert result.outcome_code == fm.ACCOUNT_UNAVAILABLE


# --- Positive path (synthetic strategy only) ---------------------------------------------------


def test_no_decisions_when_strategy_returns_no_trade():
    result = run_live_decision_cycle(
        registry=_validated_registry(), strategies_by_id={"TEST-FAKE-STRATEGY": _FakeNoTradeStrategy()},
        snapshots_by_underlying={"AAPL": _snapshot()}, risk_manager=RiskManager(_limits()), sizer=FixedQuantitySizer(1),
        account_number="ACC1", now=_now(),
    )
    assert result.outcome_code == fm.NO_DECISIONS


def test_full_positive_path_blocked_by_missing_authorization_stores():
    """Even with a (test-only) validated strategy, risk-approved sizing,
    and everything else lined up, omitting the emergency-stop/system-state
    stores must still block -- 'ready' never means 'submitted', and
    missing stores are the safe/blocked default."""
    result = run_live_decision_cycle(
        registry=_validated_registry(), strategies_by_id={"TEST-FAKE-STRATEGY": _FakeEnterStrategy()},
        snapshots_by_underlying={"AAPL": _snapshot()}, risk_manager=RiskManager(_limits()), sizer=FixedQuantitySizer(1),
        account_number="ACC1", now=_now(),
    )
    assert result.outcome_code == fm.EMERGENCY_STOP_ACTIVE
    assert result.order_request is None


def test_full_positive_path_blocked_by_unauthorized_system_state(tmp_path):
    stop_store = EmergencyStopStore(tmp_path / "stop.json")
    stop_store.clear(authorized_by="user:test", reason="test fixture")
    audit_log = SystemStateAuditLog(tmp_path / "audit.jsonl")  # no transitions recorded -- unauthorized
    result = run_live_decision_cycle(
        registry=_validated_registry(), strategies_by_id={"TEST-FAKE-STRATEGY": _FakeEnterStrategy()},
        snapshots_by_underlying={"AAPL": _snapshot()}, risk_manager=RiskManager(_limits()), sizer=FixedQuantitySizer(1),
        account_number="ACC1", now=_now(), emergency_stop_store=stop_store, system_state_audit_log=audit_log,
    )
    assert result.outcome_code == fm.NOT_AUTHORIZED
    assert result.order_request is None


def test_full_positive_path_ready_when_everything_lines_up(tmp_path):
    """The only scenario in which order_request is populated -- and even
    then, this function NEVER calls submit_order/place_option_order (see
    test_phase36_strategy_isolation.py)."""
    stop_store, audit_log = _authorized_stores(tmp_path)
    result = run_live_decision_cycle(
        registry=_validated_registry(), strategies_by_id={"TEST-FAKE-STRATEGY": _FakeEnterStrategy()},
        snapshots_by_underlying={"AAPL": _snapshot()}, risk_manager=RiskManager(_limits()), sizer=FixedQuantitySizer(1),
        account_number="ACC1", now=_now(), emergency_stop_store=stop_store, system_state_audit_log=audit_log,
    )
    assert result.outcome_code == fm.READY_FOR_AUTHORIZATION
    assert result.decision_type == DecisionType.ENTER
    assert result.order_request is not None
    assert result.order_request.legs[0].option_id == "opt-1"


def test_full_positive_path_still_blocked_if_emergency_stop_tripped_after_authorization(tmp_path):
    """Even with a fully authorized system state, a tripped emergency
    stop still blocks -- the two gates are independent (Phase 35 Part P)."""
    _, audit_log = _authorized_stores(tmp_path)
    tripped_stop = EmergencyStopStore(tmp_path / "stop2.json")  # never cleared -- defaults STOPPED
    result = run_live_decision_cycle(
        registry=_validated_registry(), strategies_by_id={"TEST-FAKE-STRATEGY": _FakeEnterStrategy()},
        snapshots_by_underlying={"AAPL": _snapshot()}, risk_manager=RiskManager(_limits()), sizer=FixedQuantitySizer(1),
        account_number="ACC1", now=_now(), emergency_stop_store=tripped_stop, system_state_audit_log=audit_log,
    )
    assert result.outcome_code == fm.EMERGENCY_STOP_ACTIVE
    assert result.order_request is None


def test_risk_rejection_blocks_before_authorization_is_even_checked(tmp_path):
    stop_store, audit_log = _authorized_stores(tmp_path)
    result = run_live_decision_cycle(
        registry=_validated_registry(), strategies_by_id={"TEST-FAKE-STRATEGY": _FakeEnterStrategy()},
        snapshots_by_underlying={"AAPL": _snapshot()}, risk_manager=RiskManager(_limits(max_trades_per_day=0)),
        sizer=FixedQuantitySizer(1), account_number="ACC1", now=_now(),
        emergency_stop_store=stop_store, system_state_audit_log=audit_log,
    )
    assert result.outcome_code == fm.RISK_REJECTED
    assert result.order_request is None
