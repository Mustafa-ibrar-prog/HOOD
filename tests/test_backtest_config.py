"""Tests for the Phase 3 extensions to BacktestConfig — additive only;
tests/test_backtesting_interfaces.py's Phase 2 test of the original 4
required + 2 optional fields is untouched and still exercises the exact
same construction call."""

from __future__ import annotations

from datetime import date

from src.backtesting.interfaces import BacktestConfig


def _minimal_config(**overrides) -> BacktestConfig:
    defaults = dict(symbols=("AAPL",), timeframe="day", start=date(2023, 1, 1), end=date(2024, 1, 1), data_version="dv", feature_version="fv")
    defaults.update(overrides)
    return BacktestConfig(**defaults)


def test_backtest_id_is_auto_generated_and_unique():
    a = _minimal_config()
    b = _minimal_config()
    assert a.backtest_id != b.backtest_id
    assert a.backtest_id.startswith("BT-")


def test_new_fields_have_safe_defaults():
    config = _minimal_config()
    assert config.strategy_name == ""
    assert config.benchmark_symbol is None
    assert config.execution_config == {}
    assert config.risk_config == {}


def test_to_dict_is_fully_serializable():
    config = _minimal_config(strategy_name="ma-crossover", execution_config={"model": "NextBarExecutionModel", "delay_bars": 1})
    d = config.to_dict()
    assert d["strategy_name"] == "ma-crossover"
    assert d["start"] == "2023-01-01"
    assert d["execution_config"] == {"model": "NextBarExecutionModel", "delay_bars": 1}
    import json

    json.dumps(d)  # must not raise — every value is JSON-serializable
