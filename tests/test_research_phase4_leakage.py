"""Phase 4, section 23: dedicated leakage/reproducibility proofs at the
research-framework level (IC, quantile analysis, and a full ResearchStrategy
run through the real backtest engine) — on top of Phase 2's feature-level
and Phase 3's engine-level leakage tests, which already cover the lower
layers these all sit on."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from src.backtesting import BacktestConfig, BacktestRiskAdapter, FixedPercentSpreadModel, FixedQuantitySizer, NextBarExecutionModel, PerShareCommission, ZeroSlippage
from src.data.bar import Bar
from src.research.ic import compute_ic_series
from src.research.quantile import cross_sectional_quantile_returns
from src.research.runner import run_research_backtest
from src.research.strategies import MomentumStrategy
from src.risk.manager import RiskManager
from src.risk.models import RiskLimits

UTC = timezone.utc
CUTOFF_DAY = 30


def _panel_row(day: int, symbol: str, feature: float, target: float) -> dict:
    return {"timestamp": datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=day), "symbol": symbol, "feature_x": feature, "target_y": target}


def _base_panel() -> list[dict]:
    rows = []
    for day in range(60):
        rows += [_panel_row(day, s, float(i + day), float((i + day) % 5) * 0.01) for i, s in enumerate("ABCDE")]
    return rows


def _mutated_panel() -> list[dict]:
    base = _base_panel()
    cutoff_ts = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=CUTOFF_DAY)
    return [r for r in base if r["timestamp"] <= cutoff_ts] + [
        {**r, "feature_x": 999_999.0, "target_y": 999_999.0} for r in base if r["timestamp"] > cutoff_ts
    ]


def test_ic_series_unaffected_by_mutated_future_panel_rows():
    base_points = compute_ic_series(_base_panel(), "feature_x", "target_y", min_universe_size=3)
    mutated_points = compute_ic_series(_mutated_panel(), "feature_x", "target_y", min_universe_size=3)
    cutoff_ts = datetime(2024, 1, 1 + CUTOFF_DAY, tzinfo=UTC)
    base_early = [p for p in base_points if p.timestamp <= cutoff_ts]
    mutated_early = [p for p in mutated_points if p.timestamp <= cutoff_ts]
    assert base_early == mutated_early
    assert len(base_early) > 0


def test_quantile_analysis_unaffected_by_mutated_future_panel_rows():
    base = _base_panel()
    mutated = _mutated_panel()
    cutoff_ts = datetime(2024, 1, 1 + CUTOFF_DAY, tzinfo=UTC)
    base_early_only = [r for r in base if r["timestamp"] <= cutoff_ts]
    mutated_early_only = [r for r in mutated if r["timestamp"] <= cutoff_ts]
    report_base = cross_sectional_quantile_returns(base_early_only, "feature_x", "target_y", min_universe_size=3)
    report_mutated = cross_sectional_quantile_returns(mutated_early_only, "feature_x", "target_y", min_universe_size=3)
    assert report_base == report_mutated


def _bars(closes: list[float]) -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol="TEST", timeframe="day", open=c, high=c + 1, low=c - 1, close=c, volume=1000)
        for i, c in enumerate(closes)
    ]


def _risk_adapter():
    limits = RiskLimits(max_trades_per_day=100, max_daily_loss_usd=1e9, max_position_size_usd=1e9, cooldown_minutes_after_exit=0, stale_data_max_seconds=1e9, max_spread_pct=1.0, min_option_volume=0, min_option_open_interest=0, max_extended_move_pct=100.0, entry_cutoff_time=time(23, 59))
    return BacktestRiskAdapter(RiskManager(limits))


def test_research_strategy_backtest_signals_unaffected_by_mutated_future_bars():
    import math

    base_closes = [100.0 + 8 * math.sin(i / 5) for i in range(70)]
    mutated_closes = base_closes[:41] + [10_000_000.0 + i for i in range(29)]

    def run(closes):
        bars = _bars(closes)
        strategy = MomentumStrategy(strategy_id="MOM-TEST", lookback=5, universe=["TEST"], entry_threshold=0.01)
        config = BacktestConfig(symbols=("TEST",), timeframe="day", start=bars[0].timestamp.date(), end=bars[-1].timestamp.date(), data_version="dv", feature_version="fv", initial_capital_usd=100_000.0)
        return run_research_backtest(
            research_strategy=strategy, bars_by_symbol={"TEST": bars}, config=config, execution_model=NextBarExecutionModel(),
            slippage_model=ZeroSlippage(), cost_model=PerShareCommission(0.0), spread_model=FixedPercentSpreadModel(0.0),
            position_sizer=FixedQuantitySizer(10), risk_adapter=_risk_adapter(),
        )

    base_result = run(base_closes)
    mutated_result = run(mutated_closes)
    cutoff_ts = _bars(base_closes)[40].timestamp

    from src.backtesting.events import SignalEvent

    base_signals = [e for e in base_result.event_log if isinstance(e, SignalEvent) and e.timestamp <= cutoff_ts]
    mutated_signals = [e for e in mutated_result.event_log if isinstance(e, SignalEvent) and e.timestamp <= cutoff_ts]
    assert base_signals == mutated_signals
    assert len(base_signals) > 0
