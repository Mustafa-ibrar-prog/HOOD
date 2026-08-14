from __future__ import annotations

from datetime import date

import pytest

from src.strategy.base import SetupCandidate, Strategy
from src.strategy.decision import Decision
from src.strategy.scanner import StrategyScanner
from tests.conftest import make_thesis


class _FakeStrategy(Strategy):
    name = "fake-strategy"

    def __init__(self, candidates):
        self._candidates = candidates

    def scan(self, market, universe):
        return list(self._candidates)


class _NotImplementedStrategy(Strategy):
    name = "unimplemented-strategy"

    def scan(self, market, universe):
        raise NotImplementedError("no data provider wired up")


def _candidate(score: float, symbol: str = "AAPL") -> SetupCandidate:
    return SetupCandidate(
        underlying_symbol=symbol,
        option_id=f"opt-{symbol}-{score}",
        option_description=f"{symbol} 2026-09-18 C 230",
        side="long_call",
        thesis=make_thesis(),
        suggested_entry_price=0.95,
        suggested_quantity=1,
        profit_target_usd=20.0,
        stop_loss_usd=15.0,
        expiration=date(2026, 9, 18),
        score=score,
    )


def test_strategy_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        Strategy()  # abstract — scan() not implemented


def test_setup_candidate_rejects_invalid_side():
    with pytest.raises(ValueError):
        SetupCandidate(
            underlying_symbol="AAPL",
            option_id="opt-1",
            option_description="AAPL call",
            side="short_call",  # not a supported Level-2 single-leg side here
            thesis=make_thesis(),
            suggested_entry_price=0.95,
            suggested_quantity=1,
            profit_target_usd=20.0,
            stop_loss_usd=15.0,
            expiration=date(2026, 9, 18),
            score=1.0,
        )


def test_scanner_requires_at_least_one_strategy():
    with pytest.raises(ValueError):
        StrategyScanner([])


def test_scanner_aggregates_and_sorts_candidates_by_score():
    strategy_a = _FakeStrategy([_candidate(0.5, "AAPL")])
    strategy_b = _FakeStrategy([_candidate(0.9, "MSFT"), _candidate(0.2, "TSLA")])
    scanner = StrategyScanner([strategy_a, strategy_b])

    result = scanner.scan_for_setups(market=None, universe=["AAPL", "MSFT", "TSLA"])

    assert [c.score for c in result.candidates] == [0.9, 0.5, 0.2]


def test_scanner_logs_no_trade_when_no_candidates_found():
    scanner = StrategyScanner([_FakeStrategy([])])
    result = scanner.scan_for_setups(market=None, universe=["AAPL"])
    assert result.candidates == ()
    assert result.decision.decision is Decision.NO_TRADE


def test_scanner_tolerates_unimplemented_strategy_without_crashing():
    scanner = StrategyScanner([_NotImplementedStrategy(), _FakeStrategy([_candidate(0.7)])])
    result = scanner.scan_for_setups(market=None, universe=["AAPL"])
    assert len(result.candidates) == 1


def test_scanner_never_itself_authorizes_a_buy():
    """Finding a candidate is not the same as approving a trade — that
    still requires the risk manager. The scanner's own decision object
    must never be BUY."""
    scanner = StrategyScanner([_FakeStrategy([_candidate(0.9)])])
    result = scanner.scan_for_setups(market=None, universe=["AAPL"])
    assert result.decision.decision is not Decision.BUY
