"""Orchestrates one or more Strategy implementations across a universe of
symbols and produces a ranked list of candidates — or an explicit NO_TRADE.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from src.strategy.base import SetupCandidate, Strategy
from src.strategy.decision import Decision, DecisionResult

if TYPE_CHECKING:
    from src.market.data_provider import MarketDataProvider


@dataclass(frozen=True)
class ScanResult:
    candidates: tuple[SetupCandidate, ...]
    decision: DecisionResult  # NO_TRADE if candidates is empty, else informational BUY-candidates summary


class StrategyScanner:
    """Runs every registered strategy and merges/ranks their output.

    This class does not itself decide to place a trade — it only produces
    ranked candidates. Turning a candidate into an actual BUY decision
    still requires passing it through the risk manager.
    """

    def __init__(self, strategies: Sequence[Strategy]):
        if not strategies:
            raise ValueError("StrategyScanner requires at least one Strategy")
        self._strategies = list(strategies)

    def scan_for_setups(self, market: "MarketDataProvider", universe: Sequence[str]) -> ScanResult:
        all_candidates: list[SetupCandidate] = []
        errors: list[str] = []

        for strategy in self._strategies:
            try:
                found = strategy.scan(market, universe)
            except NotImplementedError:
                # Expected during the foundation phase: no live data
                # provider is wired up yet. Record it, don't crash the scan.
                errors.append(f"{strategy.name}: market data provider not implemented yet")
                continue
            all_candidates.extend(found)

        all_candidates.sort(key=lambda c: c.score, reverse=True)

        if not all_candidates:
            reason = "No qualifying setups found"
            if errors:
                reason += f" ({'; '.join(errors)})"
            decision = DecisionResult(
                decision=Decision.NO_TRADE,
                reason=reason,
                confidence=1.0,
                evidence={"universe_size": len(universe), "strategies_run": len(self._strategies)},
            )
        else:
            top = all_candidates[0]
            decision = DecisionResult(
                decision=Decision.NO_TRADE,  # scanning alone never authorizes a BUY; risk gate does
                reason=(
                    f"{len(all_candidates)} candidate(s) found; top candidate "
                    f"{top.option_description} still requires risk-manager approval before any BUY"
                ),
                confidence=0.0,
                evidence={"top_candidate_score": top.score, "candidate_count": len(all_candidates)},
            )

        return ScanResult(candidates=tuple(all_candidates), decision=decision)
