"""Phase 35, Part A/T — the frozen spec must match the live source
EXACTLY. Every assertion here reads the real constant from the real
module (never a copy), so this spec can never silently drift from the
code it claims to describe -- if a future change to
`momentum_breakout.py`, `hood_provider.py`, `indicators.py`,
`evidence.py`, or `evaluator.py` alters any of these numbers, this test
suite fails immediately and loudly, exactly as Part A requires
("Do not change any of these rules before validation")."""

from __future__ import annotations

import inspect

from src.options.phase35_frozen_strategy_spec import MOMENTUM_BREAKOUT_EXISTING_V1, STRATEGY_ID


def test_strategy_id_is_the_required_format():
    assert STRATEGY_ID == "MOMENTUM_BREAKOUT_EXISTING_V1"
    assert MOMENTUM_BREAKOUT_EXISTING_V1.strategy_id == STRATEGY_ID


def test_spec_never_claims_validation():
    assert MOMENTUM_BREAKOUT_EXISTING_V1.is_validated is False


def test_class_and_file_location_are_real():
    from src.strategy.momentum_breakout import MomentumBreakoutStrategy

    assert MOMENTUM_BREAKOUT_EXISTING_V1.class_name == MomentumBreakoutStrategy.__name__
    assert inspect.getsourcefile(MomentumBreakoutStrategy).endswith(MOMENTUM_BREAKOUT_EXISTING_V1.file_location)


def test_option_selection_matches_live_momentum_breakout_config():
    from src.strategy.momentum_breakout import MomentumBreakoutConfig

    live = MomentumBreakoutConfig()
    spec = MOMENTUM_BREAKOUT_EXISTING_V1.option_selection
    assert spec.min_days_to_expiration == live.min_days_to_expiration
    assert spec.max_days_to_expiration == live.max_days_to_expiration
    assert spec.prefilter_max_spread_pct == live.max_spread_pct
    assert spec.prefilter_min_volume == live.min_volume
    assert spec.prefilter_min_open_interest == live.min_open_interest


def test_position_sizing_matches_live_momentum_breakout_config():
    from src.strategy.momentum_breakout import MomentumBreakoutConfig

    live = MomentumBreakoutConfig()
    spec = MOMENTUM_BREAKOUT_EXISTING_V1.position_sizing
    assert spec.profit_target_pct_of_premium == live.profit_target_pct
    assert spec.stop_loss_pct_of_premium == live.stop_loss_pct


def test_position_sizing_matches_live_contract_multiplier():
    from src.config.constants import CONTRACT_MULTIPLIER

    assert MOMENTUM_BREAKOUT_EXISTING_V1.position_sizing.contract_multiplier == CONTRACT_MULTIPLIER


def test_underlying_signal_bar_source_matches_live_provider_defaults():
    from src.market.hood_provider import HoodMarketDataProvider

    live_defaults = inspect.signature(HoodMarketDataProvider.__init__).parameters
    spec = MOMENTUM_BREAKOUT_EXISTING_V1.underlying_signals
    assert spec.bar_interval == live_defaults["history_interval"].default
    assert spec.history_lookback_minutes == live_defaults["history_lookback_minutes"].default
    assert spec.rsi_period == live_defaults["rsi_period"].default
    assert spec.ema_fast_period == live_defaults["ema_fast_period"].default
    assert spec.ema_slow_period == live_defaults["ema_slow_period"].default


def test_underlying_signal_structure_detector_defaults_match_live_indicators():
    from src.market.indicators import detect_breakout_continuation, detect_failed_breakout, higher_highs_lower_highs, macd

    spec = MOMENTUM_BREAKOUT_EXISTING_V1.underlying_signals
    hh_params = inspect.signature(higher_highs_lower_highs).parameters
    assert spec.higher_lower_highs_lookback_bars == hh_params["lookback"].default

    bc_params = inspect.signature(detect_breakout_continuation).parameters
    assert spec.breakout_resistance_lookback_bars == bc_params["resistance_lookback"].default
    assert spec.breakout_confirm_bars == bc_params["confirm_bars"].default

    fb_params = inspect.signature(detect_failed_breakout).parameters
    assert spec.failed_breakout_resistance_lookback_bars == fb_params["resistance_lookback"].default

    macd_params = inspect.signature(macd).parameters
    assert spec.macd_fast_period == macd_params["fast"].default
    assert spec.macd_slow_period == macd_params["slow"].default
    assert spec.macd_signal_period == macd_params["signal"].default


def test_momentum_evidence_thresholds_match_live_evidence_module():
    from src.strategy import evidence as evidence_module

    spec = MOMENTUM_BREAKOUT_EXISTING_V1.underlying_signals
    assert spec.weakening_threshold == evidence_module.WEAKENING_THRESHOLD
    assert spec.reversing_threshold == evidence_module.REVERSING_THRESHOLD
    assert spec.requires_momentum_state == evidence_module.MomentumState.STRENGTHENING.value


def test_exit_spec_matches_live_evaluator_config_defaults():
    from src.position_manager.evaluator import EvaluatorConfig

    live = EvaluatorConfig()
    spec = MOMENTUM_BREAKOUT_EXISTING_V1.exit
    assert spec.min_weakening_signals_for_exit == live.min_weakening_signals_for_exit
    assert spec.expiration_buffer_minutes == live.expiration_buffer_minutes
    assert spec.trailing_arm_fraction == live.trailing_arm_fraction
    assert spec.trailing_giveback_fraction == live.trailing_giveback_fraction


def test_exit_spec_matches_live_settings_trailing_defaults():
    """orchestrator.py wires EvaluatorConfig from Settings.trailing_arm_fraction/
    trailing_giveback_fraction in normal use -- confirm Settings' own
    defaults agree with EvaluatorConfig's bare defaults (both should
    describe the same real, running behavior)."""
    from src.config.settings import Settings

    defaults = inspect.signature(Settings.from_env).parameters  # from_env has no defaults of its own; check the dataclass field defaults instead
    # Settings has no dataclass field defaults (all sourced via from_env's _get_float calls) --
    # assert directly against the literal defaults passed to _get_float in from_env's source.
    import ast
    from pathlib import Path

    source = Path(inspect.getsourcefile(Settings)).read_text()
    tree = ast.parse(source)
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_get_float":
            args = node.args
            if len(args) >= 3 and isinstance(args[1], ast.Constant) and args[1].value in ("TRAILING_ARM_FRACTION", "TRAILING_GIVEBACK_FRACTION"):
                found[args[1].value] = args[2].value
    assert found.get("TRAILING_ARM_FRACTION") == MOMENTUM_BREAKOUT_EXISTING_V1.exit.trailing_arm_fraction
    assert found.get("TRAILING_GIVEBACK_FRACTION") == MOMENTUM_BREAKOUT_EXISTING_V1.exit.trailing_giveback_fraction


def test_calls_only_thesis_direction_matches_live_docstring_claim():
    """The strategy's own module docstring says 'CALLS ONLY' -- confirm
    the live code structurally cannot select a put (type='call' is
    passed verbatim to get_option_chain_candidates)."""
    source = inspect.getsource(__import__("src.strategy.momentum_breakout", fromlist=["_"]))
    assert 'type="call"' in source or "type='call'" in source
    assert MOMENTUM_BREAKOUT_EXISTING_V1.option_selection.option_type == "call"
    assert MOMENTUM_BREAKOUT_EXISTING_V1.underlying_signals.thesis_direction == "bullish"
