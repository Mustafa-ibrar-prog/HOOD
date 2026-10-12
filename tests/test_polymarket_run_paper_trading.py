"""Tests for scripts/run_paper_trading.py -- the command that MUST
NEVER submit a real order, even if POLYMARKET_TRADING_MODE=live leaks
into its environment. Everything below reuses the same fake-client/
fake-Coinbase-source harness test_run_polymarket_bot_loop.py already
established for scripts.run_polymarket_bot.run_bot(), since
run_paper_trading.py calls that exact same function."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.run_paper_trading as paper  # noqa: E402
import scripts.run_polymarket_bot as bot  # noqa: E402
from src.polymarket.engine import CycleReport  # noqa: E402
from src.polymarket.gateway import PaperPolymarketGateway  # noqa: E402
from src.polymarket.settings import PolymarketSettings, TRADING_MODE_LIVE, TRADING_MODE_PAPER  # noqa: E402

_VALID_PRIVATE_KEY = "0x" + "a" * 64  # fake-but-correctly-shaped, same convention as test_polymarket_settings.py


class _FakeCoinbaseSource:
    name = "fake-coinbase"

    def get_recent_candles(self, *, limit: int):
        return []


def _isolated_settings(tmp_path: Path, **overrides) -> PolymarketSettings:
    env = {
        "POLYMARKET_BTC_PRICE_HISTORY_FILE": str(tmp_path / "btc.json"),
        "POLYMARKET_DECISION_LOG_FILE": str(tmp_path / "decisions.jsonl"),
        "POLYMARKET_PENDING_ORDERS_FILE": str(tmp_path / "pending.json"),
        "POLYMARKET_EMERGENCY_STOP_FILE": str(tmp_path / "estop.json"),
        "POLYMARKET_DAILY_PNL_FILE": str(tmp_path / "pnl.json"),
        "POLYMARKET_POSITIONS_FILE": str(tmp_path / "positions.json"),
        "POLYMARKET_POLL_INTERVAL_SECONDS": "1",
        **overrides,
    }
    return PolymarketSettings.from_env(env=env)


def _run(monkeypatch, tmp_path, *, settings_overrides: dict | None = None, max_cycles: int = 1, captured_gateways: list | None = None):
    settings = _isolated_settings(tmp_path, **(settings_overrides or {}))
    monkeypatch.setattr(paper.PolymarketSettings, "from_env", staticmethod(lambda env=None: settings))
    monkeypatch.setattr(bot, "get_polymarket_client", lambda settings: object())
    monkeypatch.setattr(bot, "CoinbaseBtcQuoteSource", lambda: _FakeCoinbaseSource())

    def fake_run_cycle(**kwargs):
        if captured_gateways is not None:
            captured_gateways.append(kwargs["gateway"])
        return CycleReport(ran=True)

    monkeypatch.setattr(bot, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(bot.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(sys, "argv", ["run_paper_trading.py", "--max-cycles", str(max_cycles)])
    return paper.main()


def test_paper_trading_command_always_uses_the_paper_gateway_even_if_env_says_live(monkeypatch, tmp_path):
    gateways: list = []
    rc = _run(
        monkeypatch, tmp_path,
        settings_overrides={
            "POLYMARKET_TRADING_MODE": "live", "POLYMARKET_LIVE_TRADING_CONFIRMED": "true",
            "POLYMARKET_PRIVATE_KEY": _VALID_PRIVATE_KEY,
        },
        captured_gateways=gateways,
    )
    assert rc == 0
    assert len(gateways) == 1
    assert isinstance(gateways[0], PaperPolymarketGateway)  # NEVER a live gateway, regardless of env


def test_paper_trading_command_prints_a_warning_when_env_requested_live(monkeypatch, tmp_path, capsys):
    _run(monkeypatch, tmp_path, settings_overrides={
        "POLYMARKET_TRADING_MODE": "live", "POLYMARKET_LIVE_TRADING_CONFIRMED": "true", "POLYMARKET_PRIVATE_KEY": _VALID_PRIVATE_KEY,
    })
    out = capsys.readouterr().out
    assert "FORCES paper mode" in out


def test_paper_trading_command_with_an_already_paper_env_runs_quietly(monkeypatch, tmp_path, capsys):
    rc = _run(monkeypatch, tmp_path, settings_overrides={"POLYMARKET_TRADING_MODE": "paper"})
    assert rc == 0
    out = capsys.readouterr().out
    assert "FORCES paper mode" not in out  # no need to warn -- it was already paper


def test_paper_trading_command_uses_the_same_run_cycle_as_live_mode(monkeypatch, tmp_path):
    """run_paper_trading.py must call scripts.run_polymarket_bot.run_bot(),
    which calls the exact same run_cycle() live mode calls -- never a
    separate, parallel decision path for paper mode."""
    calls = []

    def fake_run_bot(settings, **kwargs):
        calls.append((settings, kwargs))
        return 0

    monkeypatch.setattr(paper, "run_bot", fake_run_bot)
    fixed_settings = _isolated_settings(tmp_path, POLYMARKET_TRADING_MODE="paper")
    monkeypatch.setattr(paper.PolymarketSettings, "from_env", staticmethod(lambda env=None: fixed_settings))
    monkeypatch.setattr(sys, "argv", ["run_paper_trading.py", "--once"])

    paper.main()

    assert len(calls) == 1
    settings_passed, kwargs_passed = calls[0]
    assert settings_passed.is_paper
    assert kwargs_passed == {"once": True, "max_cycles": None}


def test_forced_paper_settings_object_is_actually_paper():
    import dataclasses
    settings = PolymarketSettings.from_env(env={
        "POLYMARKET_TRADING_MODE": "live", "POLYMARKET_LIVE_TRADING_CONFIRMED": "true", "POLYMARKET_PRIVATE_KEY": _VALID_PRIVATE_KEY,
    })
    forced = dataclasses.replace(settings, trading_mode=TRADING_MODE_PAPER)
    assert forced.is_paper
    assert not forced.is_live
    assert settings.trading_mode == TRADING_MODE_LIVE  # the original object is untouched -- immutable dataclass
