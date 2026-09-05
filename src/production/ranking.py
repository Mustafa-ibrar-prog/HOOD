"""Phase 36, Part 13 — ranking multiple qualifying opportunities without
embedding new alpha logic inside the execution engine.

The composite score below is a RANKING heuristic over fields the
strategy/liquidity layers already produced (strategy score, liquidity,
spread, affordability, concentration) -- it never computes a new
predictive signal, never reads price history, and never substitutes for
a strategy's own `signal_score`/`confidence`. If that distinction ever
blurs, this stops being "ranking" and becomes an undeclared second
strategy, which this module explicitly must not be
(`tests/test_phase36_ranking.py::test_ranking_never_imports_a_signal_or_indicator_module`
checks this structurally).

Part 13's fail-closed requirement ("if no validated strategy exists, the
ranking pipeline must return NO_VALIDATED_STRATEGY rather than selecting
a trade") is enforced here too, in ADDITION to pipeline.py's own earlier
gate -- belt-and-braces, so this module is never accidentally safe only
because of what calls it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.production.liquidity import LiquidityClassification
from src.production.opportunity import Opportunity
from src.production.snapshot import AccountState

NO_VALIDATED_STRATEGY = "NO_VALIDATED_STRATEGY"

_LIQUIDITY_SCORE = {
    LiquidityClassification.LIQUID: 1.0,
    LiquidityClassification.MARGINAL: 0.5,
    LiquidityClassification.ILLIQUID: 0.0,
    LiquidityClassification.UNKNOWN: 0.0,
}


@dataclass(frozen=True)
class RankedOpportunity:
    opportunity: Opportunity
    composite_score: float
    concentration_penalty_applied: bool
    affordability_penalty_applied: bool


def score_opportunity(opportunity: Opportunity, *, account: AccountState, held_underlyings: frozenset[str]) -> RankedOpportunity:
    base = opportunity.decision.signal_score or 0.0
    confidence_bonus = (opportunity.confidence or 0.0) * 0.1
    liquidity_component = _LIQUIDITY_SCORE[opportunity.liquidity.classification]
    spread_penalty = (opportunity.liquidity.spread_pct or 1.0) * 0.5

    concentration_penalty_applied = opportunity.underlying in held_underlyings
    concentration_penalty = 1.0 if concentration_penalty_applied else 0.0

    affordability_penalty_applied = False
    affordability_bonus = 0.0
    if opportunity.estimated_maximum_loss_usd is not None and account.buying_power_usd is not None:
        if opportunity.estimated_maximum_loss_usd > account.buying_power_usd:
            affordability_penalty_applied = True
        else:
            affordability_bonus = 0.1

    composite = (
        base + confidence_bonus + liquidity_component + affordability_bonus
        - spread_penalty - concentration_penalty - (10.0 if affordability_penalty_applied else 0.0)
    )
    return RankedOpportunity(opportunity, composite, concentration_penalty_applied, affordability_penalty_applied)


def rank_opportunities(
    opportunities: Sequence[Opportunity], *, account: AccountState, held_underlyings: frozenset[str] = frozenset(),
) -> list[RankedOpportunity]:
    scored = [score_opportunity(o, account=account, held_underlyings=held_underlyings) for o in opportunities]
    return sorted(scored, key=lambda r: r.composite_score, reverse=True)


def rank_or_no_validated_strategy(
    opportunities: Sequence[Opportunity], *, has_validated_strategy: bool, account: AccountState,
    held_underlyings: frozenset[str] = frozenset(),
) -> list[RankedOpportunity] | str:
    """Returns the literal string NO_VALIDATED_STRATEGY (never a ranked
    list, never an implicit empty-list "no opportunities" ambiguity) when
    `has_validated_strategy` is False -- regardless of how many
    `opportunities` were passed in (which, if this is called correctly by
    a fail-closed pipeline, should always be empty in that case anyway)."""
    if not has_validated_strategy:
        return NO_VALIDATED_STRATEGY
    return rank_opportunities(opportunities, account=account, held_underlyings=held_underlyings)
