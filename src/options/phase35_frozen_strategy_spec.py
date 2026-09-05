"""Phase 35, Part A/T — the canonical, immutable specification of the
EXISTING `MomentumBreakoutStrategy` (`src/strategy/momentum_breakout.py`)
as it is actually implemented today, plus the SHARED exit machinery every
live position (regardless of which strategy opened it) goes through
(`src/position_manager/evaluator.py`'s `PositionEvaluator`).

This module changes NO behavior. It is pure documentation-as-code: every
field below is transcribed directly from the real, running source, and
`tests/test_phase35_frozen_strategy_spec.py` asserts each one against
the live constants so this spec cannot silently drift from the code it
describes. Freezing it here (Part A's explicit instruction: "Do not
change any of these rules before validation") is what lets the rest of
Phase 35 test THIS exact strategy, not a paraphrase of it.

Strategy ID: `MOMENTUM_BREAKOUT_EXISTING_V1`. Calling it "frozen" is not
the same as calling it "validated" — Part A: "Do not call it validated.
It is simply the frozen candidate under test." No claim about its
performance or validity is made anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

STRATEGY_ID = "MOMENTUM_BREAKOUT_EXISTING_V1"
FROZEN_AS_OF = "2026-09-04"  # the date this spec was transcribed from the live source, Phase 35


@dataclass(frozen=True)
class UnderlyingSignalSpec:
    """Part A: "underlying signals." Transcribed from
    `src/strategy/momentum_breakout.py::_scan_symbol` and
    `src/strategy/evidence.py::evaluate_momentum`. Every underlying
    indicator is computed LOCALLY (never fetched from a technical-
    indicators tool) by `src/market/indicators.py`, over bars supplied by
    `MarketDataProvider.get_underlying_snapshot` — see
    `bar_interval`/`history_lookback_minutes` below for the EXACT bars
    used in the live/default configuration."""

    # --- Bar source (src/market/hood_provider.py::HoodMarketDataProvider.__init__ defaults) ---
    bar_interval: str = "5minute"
    history_lookback_minutes: int = 180  # ~36 five-minute bars in a regular session

    # --- Indicator periods (same file's constructor defaults) ---
    rsi_period: int = 14
    ema_fast_period: int = 9
    ema_slow_period: int = 21
    macd_fast_period: int = 12  # src/market/indicators.py::macd's own default
    macd_slow_period: int = 26
    macd_signal_period: int = 9

    # --- Structure detectors (src/market/indicators.py defaults, called with no override) ---
    higher_lower_highs_lookback_bars: int = 5
    breakout_resistance_lookback_bars: int = 20
    breakout_confirm_bars: int = 2
    failed_breakout_resistance_lookback_bars: int = 20

    # --- Momentum-evidence scoring thresholds (src/strategy/evidence.py) ---
    weakening_threshold: int = 3
    reversing_threshold: int = 5
    min_required_fields_for_a_verdict: int = 3  # below this, INSUFFICIENT_DATA (never a guess)

    # --- Entry gate (src/strategy/momentum_breakout.py::_scan_symbol) ---
    requires_breakout_continuation: bool = True  # hard gate -- not just "looks okay"
    requires_momentum_state: str = "STRENGTHENING"  # must equal evaluate_momentum's verdict exactly
    thesis_direction: str = "bullish"  # CALLS ONLY -- no bearish/put-side detector exists


@dataclass(frozen=True)
class OptionSelectionSpec:
    """Part A: "option-selection logic," "option type," "strike
    selection," "expiration selection." Transcribed from
    `MomentumBreakoutConfig` and `_select_contract`/`_select_expiration`."""

    option_type: str = "call"  # calls only, by explicit design (module docstring: "Scope, deliberately: CALLS ONLY")
    min_days_to_expiration: int = 7
    max_days_to_expiration: int = 45
    expiration_rule: str = "nearest real expiration whose DTE falls within [min_days_to_expiration, max_days_to_expiration], via get_option_expirations"
    strike_rule: str = "the real, tradable strike with the smallest |strike - underlying_last_trade_price| among candidates returned for the selected expiration"
    chain_filters: tuple[str, ...] = ("type=call", "state=active", "tradability=tradable")

    # --- Contract-level liquidity PRE-FILTER (strategy's own gate; NOT the authoritative
    # live gate -- RiskManager.evaluate_new_trade re-validates independently at entry time,
    # per momentum_breakout.py's own comment: "PRE-FILTER only; RiskManager enforces the
    # real limit at entry") ---
    prefilter_max_spread_pct: float = 0.15
    prefilter_min_volume: int = 10
    prefilter_min_open_interest: int = 50

    entry_price_rule: str = "the live ask price (a marketable buy-to-open limit); rejected if <= 0"


@dataclass(frozen=True)
class PositionSizingSpec:
    """Part A: "position sizing." Transcribed from `_scan_symbol`'s
    `SetupCandidate` construction plus `RiskManager.check_position_size`
    (the actual live gate)."""

    suggested_quantity: int = 1  # hardcoded -- not dynamically sized by anything in the live strategy
    profit_target_pct_of_premium: float = 0.50  # SetupCandidate.profit_target_usd = entry_price * 100 * 0.50
    stop_loss_pct_of_premium: float = 0.50  # SetupCandidate.stop_loss_usd = entry_price * 100 * 0.50
    contract_multiplier: int = 100
    live_gate_is_a_flat_usd_cap: bool = True  # RiskManager.check_position_size: proposed_size_usd <= Settings.max_position_size_usd (config, default $250) -- not derived from this strategy


@dataclass(frozen=True)
class ExitSpec:
    """Part A: "exit conditions," "stop loss," "profit taking," "time
    exit," "maximum holding period." IMPORTANT: exit logic is NOT
    strategy-specific code inside momentum_breakout.py -- every open
    position, from any strategy, is evaluated by the SAME SHARED
    `PositionEvaluator.evaluate()` (`src/position_manager/evaluator.py`).
    Transcribed from that module and its `EvaluatorConfig` defaults
    (which mirror `Settings.trailing_arm_fraction`/
    `trailing_giveback_fraction`'s own defaults for normal use)."""

    # Priority order exactly as implemented (first match wins):
    priority_order: tuple[str, ...] = (
        "1_thesis_invalidated_stop",  # highest priority hard stop; momentum_breakout.py's own invalidation text: "Underlying closes back below the breakout level, or momentum evidence turns WEAKENING/REVERSING"
        "2_hard_stop_loss",  # pnl_usd <= -stop_loss_usd; never overridden by momentum reasoning
        "3_expiration_risk",  # inside expiration_buffer_minutes of expiration-day close: TARGET_EXIT if profitable, STOP_EXIT if not
        "4_trailing_exit",  # deterministic, price-only, independent of momentum evidence (see trailing_arm_fraction/trailing_giveback_fraction below)
        "5_insufficient_data_hold",  # fail-safe: never guesses
        "6_momentum_driven_early_exit",  # profitable + WEAKENING/REVERSING with >= min_weakening_signals_for_exit corroborating signals -- exits before the target
        "7_profit_target_reached",  # HOLD (let it run) if momentum is STRENGTHENING at the target; otherwise TARGET_EXIT
        "8_default_hold",
    )

    stop_loss_usd_source: str = "position.stop_loss_usd (set at entry = entry_price * 100 * 0.50, PositionSizingSpec.stop_loss_pct_of_premium)"
    profit_target_usd_source: str = "position.profit_target_usd (set at entry = entry_price * 100 * 0.50, PositionSizingSpec.profit_target_pct_of_premium)"

    expiration_buffer_minutes: float = 30.0
    min_weakening_signals_for_exit: int = 2

    trailing_arm_fraction: float = 0.5  # trailing protection arms once unrealized gain reaches this fraction of the entry-to-target distance
    trailing_giveback_fraction: float = 0.3  # once armed, exits if price gives back this fraction of the gain from entry to the position's peak-so-far

    maximum_holding_period_rule: str = (
        "No fixed day/bar count. A position is forced closed no later than "
        "expiration_buffer_minutes before expiration-day market close (rule 3 above); "
        "it may exit earlier via any of rules 1/2/4/6/7."
    )


@dataclass(frozen=True)
class FrozenStrategySpec:
    strategy_id: str
    frozen_as_of: str
    file_location: str
    class_name: str
    callable_entry_point: str
    dependencies: tuple[str, ...]
    orchestrator_integration: str
    underlying_signals: UnderlyingSignalSpec
    option_selection: OptionSelectionSpec
    position_sizing: PositionSizingSpec
    exit: ExitSpec
    position_assumptions: tuple[str, ...]
    is_validated: bool = False  # Part A: "Do not call it validated." Always False in this module.


def build_frozen_strategy_definition(*, development_universe_name: str, frozen_at=None):
    """Registers `MOMENTUM_BREAKOUT_EXISTING_V1` into the SAME established,
    content-hash-verified, append-only `FrozenStrategyStore` mechanism
    Phase 6 built (`src.research.frozen_strategy.FrozenStrategyDefinition`)
    -- reuse, not a parallel freezing concept. `FrozenStrategyDefinition`'s
    schema was shaped for a single-indicator/single-threshold strategy
    (MR-002); MomentumBreakoutStrategy's richer, priority-ordered,
    multi-indicator rule set is mapped into its generic
    entry_rule/exit_rule text fields and risk_configuration/position_sizing
    dicts (the exact pattern MR-002's own `frozen_rationale`/`risk_configuration`
    already uses for anything that doesn't fit a bare float). The precise,
    field-by-field, test-verified numbers live in `MOMENTUM_BREAKOUT_EXISTING_V1`
    above (this module's own dataclasses) -- this function is the
    established-store registration, not a replacement source of truth."""
    from datetime import datetime, timezone

    from src.research.frozen_strategy import FrozenStrategyDefinition

    spec = MOMENTUM_BREAKOUT_EXISTING_V1
    u, o, p, e = spec.underlying_signals, spec.option_selection, spec.position_sizing, spec.exit
    return FrozenStrategyDefinition(
        strategy_id=STRATEGY_ID, strategy_version="1.0", hypothesis_id=STRATEGY_ID,
        feature_definition=(
            f"RSI({u.rsi_period}), MACD({u.macd_fast_period},{u.macd_slow_period},{u.macd_signal_period}) histogram, "
            f"EMA({u.ema_fast_period})/EMA({u.ema_slow_period}), higher/lower-highs over {u.higher_lower_highs_lookback_bars} bars, "
            f"breakout_continuation/failed_breakout over {u.breakout_resistance_lookback_bars}+{u.breakout_confirm_bars} bars, "
            f"volume_ratio -- all computed causally from {u.bar_interval} bars, {u.history_lookback_minutes}-minute lookback "
            f"(src/market/indicators.py, unchanged), scored by evaluate_momentum (src/strategy/evidence.py, unchanged)."
        ),
        entry_rule=(
            f"LONG (buy-to-open 1 {o.option_type} contract) when breakout_continuation is True AND "
            f"evaluate_momentum(...).state == {u.requires_momentum_state!r} (thesis_direction={u.thesis_direction!r}); "
            f"contract = nearest-strike-to-underlying-price real tradable {o.option_type} with DTE in "
            f"[{o.min_days_to_expiration},{o.max_days_to_expiration}], entry price = live ask, pre-filtered by "
            f"spread<={o.prefilter_max_spread_pct}, volume>={o.prefilter_min_volume}, OI>={o.prefilter_min_open_interest} "
            f"(non-authoritative -- RiskManager.evaluate_new_trade re-validates independently at entry)."
        ),
        exit_rule=(
            "Shared PositionEvaluator.evaluate() (src/position_manager/evaluator.py, unchanged), priority order: "
            + " -> ".join(e.priority_order)
            + f". stop_loss_usd=profit_target_usd=entry_price*100*{p.stop_loss_pct_of_premium}; "
              f"expiration_buffer_minutes={e.expiration_buffer_minutes}; min_weakening_signals_for_exit={e.min_weakening_signals_for_exit}; "
              f"trailing_arm_fraction={e.trailing_arm_fraction}; trailing_giveback_fraction={e.trailing_giveback_fraction}. "
            + e.maximum_holding_period_rule
        ),
        holding_period_bars=0,  # no fixed bar count -- see exit_rule's maximum_holding_period_rule text; 0 signals "not bar-count-bounded", never a fabricated number
        lookback=u.breakout_resistance_lookback_bars,  # the single largest lookback among the multi-indicator set, for FrozenStrategyDefinition's generic int field
        entry_threshold=0.0,  # entry is a multi-signal boolean gate, not a single scalar threshold -- see entry_rule text; 0.0 is a placeholder, never a fabricated real threshold
        exit_threshold=0.0,  # same -- see exit_rule text
        prediction_horizon_bars=0,  # not horizon-based; see exit_rule
        position_sizing={"sizer": "FixedQuantitySizer", "quantity": p.suggested_quantity, "contract_multiplier": p.contract_multiplier},
        risk_configuration={
            "live_gate": "RiskManager.check_position_size, flat USD cap (Settings.max_position_size_usd)",
            "note": "reuses src.risk.manager.RiskManager unmodified, via src.backtesting.risk_adapter.BacktestRiskAdapter",
        },
        execution_model={"type": "NextBarExecutionModel", "price_field": "open", "delay_bars": 1},
        slippage_model={"type": "documented per Phase 35 Part H cost-stress sweep -- see docs/phase35_strategy_validation_and_execution_hardening.md"},
        transaction_cost_model={"type": "documented per Phase 35 Part H cost-stress sweep -- see docs/phase35_strategy_validation_and_execution_hardening.md"},
        spread_model={"type": "RealBidAskSpreadModel where a real option quote exists, FixedPercentSpreadModel fallback, source-labeled per trade"},
        starting_cash_usd=1000.0,  # Part G's $1,000 account
        development_universe_name=development_universe_name,
        frozen_at=frozen_at or datetime.now(timezone.utc),
        frozen_rationale=(
            "Phase 35 Part A: freezing the EXISTING, already-live-wired MomentumBreakoutStrategy exactly as "
            "implemented, before any validation is attempted -- not a claim of validity. See "
            "MOMENTUM_BREAKOUT_EXISTING_V1 (this module) for the exact, test-verified field-by-field specification."
        ),
    )


MOMENTUM_BREAKOUT_EXISTING_V1 = FrozenStrategySpec(
    strategy_id=STRATEGY_ID,
    frozen_as_of=FROZEN_AS_OF,
    file_location="src/strategy/momentum_breakout.py",
    class_name="MomentumBreakoutStrategy",
    callable_entry_point="MomentumBreakoutStrategy.scan(market: MarketDataProvider, universe: Sequence[str]) -> list[SetupCandidate]",
    dependencies=(
        "src.market.data_provider.MarketDataProvider",
        "src.market.errors.MarketDataError",
        "src.market.indicators (bid_ask_spread_pct, is_liquid)",
        "src.strategy.base (SetupCandidate, Strategy)",
        "src.strategy.decision (TradeThesis)",
        "src.strategy.evidence (MomentumEvidence, MomentumState, evaluate_momentum)",
        "-- exit path (shared, not strategy-owned) --",
        "src.position_manager.evaluator (PositionEvaluator, EvaluatorConfig, PositionSnapshot)",
        "src.position_manager.models.OpenPosition",
    ),
    orchestrator_integration=(
        "src/orchestrator.py::run_trading_cycle instantiates "
        "StrategyScanner([MomentumBreakoutStrategy(now=now)]) every cycle and calls "
        "scanner.scan_for_setups(market_data, settings.scan_universe); each SetupCandidate is "
        "re-validated by RiskManager.evaluate_new_trade against fresh data before "
        "_submit_entry_order() is called. This is the ONLY concrete Strategy subclass "
        "wired into the live cycle (Phase 34's audit)."
    ),
    underlying_signals=UnderlyingSignalSpec(),
    option_selection=OptionSelectionSpec(),
    position_sizing=PositionSizingSpec(),
    exit=ExitSpec(),
    position_assumptions=(
        "Single-leg, long-only. side is hard-validated to 'long_call' by this strategy "
        "(SetupCandidate.side='long_call', evidence.py's thesis_direction='bullish').",
        "One contract per entry (suggested_quantity=1) -- not dynamically sized.",
        "One new entry per scanned symbol per cycle at most; MAX_NEW_ENTRIES_PER_CYCLE "
        "(Settings, default 1) further caps total new entries across the whole universe per cycle.",
        "A symbol already held (paper or real) is skipped by RiskManager.check_duplicate_position "
        "before this strategy's candidate can be entered again.",
    ),
)
