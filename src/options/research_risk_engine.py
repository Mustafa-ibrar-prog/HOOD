"""Phase 30, Part 8/17 — the research portfolio risk-engine interface.

A NEW module, not a modification of `src/risk/manager.py`: that module
is `RiskManager`, the LIVE per-trade entry/exit GATE (max trades/day,
daily loss, duplicate position, cooldown, ...) the orchestrator already
calls before placing a real order -- a different job from this phase's
requirement, which is a PORTFOLIO-level risk VIEW across a set of
research positions (Part 7's `PositionSnapshot`s): capital at risk,
concentration, correlated positions, gap risk, assignment/exercise risk.
This module shares `src/risk/manager.py`'s `RiskCheckResult`-style
pattern (a `passed`/`code`/`message` record, aggregated into a decision
object) deliberately -- the established "reuse the pattern, not force a
fit" precedent -- rather than importing `RiskManager` itself, since none
of its eleven checks apply to a standing portfolio snapshot.

CONFIGURABLE, NEVER HARD-CODED CONSERVATIVE (Part 8's explicit
instruction: "do NOT hard-code artificially conservative limits like
'never risk more than 1%' unless research-justified"): every limit in
`ResearchRiskLimits` defaults to `None`, meaning "no limit configured" --
a check whose limit is `None` is reported as `NOT_CONFIGURED`, not
silently passed and not defaulted to some invented conservative number.
A caller who wants an active limit must set one explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.options.research_dataset import DataQualityStatus, ResearchObservation
from src.options.research_position_view import PositionSnapshot


@dataclass(frozen=True)
class ResearchRiskLimits:
    max_capital_at_risk_pct: float | None = None
    max_single_position_pct: float | None = None
    max_single_underlying_concentration_pct: float | None = None
    max_single_expiration_concentration_pct: float | None = None
    max_correlated_group_concentration_pct: float | None = None
    max_spread_pct: float | None = None
    min_liquidity_volume: float | None = None
    min_liquidity_open_interest: float | None = None
    max_recent_gap_move_pct: float | None = None
    assignment_risk_dte_threshold: int | None = None  # e.g. 2 -- flag short ITM legs within this many days of expiration
    reject_on_flagged_critical_quality: bool = True


@dataclass(frozen=True)
class RiskCheckResult:
    code: str
    passed: bool  # True if within limit OR limit not configured (NOT_CONFIGURED is never a failure)
    message: str


@dataclass(frozen=True)
class PortfolioRiskAssessment:
    account_equity_usd: float
    position_count: int
    total_capital_at_risk_usd: float | None  # sum of max_loss across positions with a determinable max_loss
    capital_at_risk_is_partial: bool  # True if >=1 position's max_loss is None/unbounded (UNSUPPORTED_STRUCTURE or naked short)
    capital_at_risk_pct: float | None
    underlying_concentration_pct: dict[str, float]
    expiration_concentration_pct: dict[str, float]
    correlated_group_concentration_pct: dict[str, float]
    results: tuple[RiskCheckResult, ...]

    @property
    def any_check_failed(self) -> bool:
        return any(not r.passed for r in self.results)

    @property
    def failing_codes(self) -> tuple[str, ...]:
        return tuple(r.code for r in self.results if not r.passed)


def _position_underlyings(snapshot: PositionSnapshot) -> tuple[str, ...]:
    return tuple(sorted({leg.underlying for leg in snapshot.legs}))


def _position_expirations(snapshot: PositionSnapshot) -> tuple:
    return tuple(sorted({leg.expiration for leg in snapshot.legs}))


def _concentration(snapshots: list[PositionSnapshot], *, key_fn, total_capital: float) -> dict[str, float]:
    """Attributes each position's capital-at-risk fully to its single
    key (underlying/expiration) only when the position is unambiguous
    (exactly one distinct key across its legs); positions spanning
    multiple keys are excluded (never proportionally guessed)."""
    if total_capital <= 0:
        return {}
    totals: dict[str, float] = {}
    for s in snapshots:
        if s.max_loss is None:
            continue
        keys = key_fn(s)
        if len(keys) != 1:
            continue
        totals[keys[0]] = totals.get(keys[0], 0.0) + s.max_loss
    return {k: v / total_capital for k, v in totals.items()}


def assess_portfolio_risk(
    snapshots: list[PositionSnapshot], *,
    account_equity_usd: float,
    limits: ResearchRiskLimits = ResearchRiskLimits(),
    correlated_groups: dict[str, str] | None = None,
    liquidity_by_contract: dict[str, ResearchObservation] | None = None,
    underlying_prices: dict[str, float] | None = None,
) -> PortfolioRiskAssessment:
    correlated_groups = correlated_groups or {}
    liquidity_by_contract = liquidity_by_contract or {}
    underlying_prices = underlying_prices or {}

    determinable = [s for s in snapshots if s.max_loss is not None]
    total_capital_at_risk = sum(s.max_loss for s in determinable) if determinable else (0.0 if snapshots else None)
    capital_partial = len(determinable) != len(snapshots)
    capital_pct = (total_capital_at_risk / account_equity_usd) if (total_capital_at_risk is not None and account_equity_usd > 0) else None

    underlying_conc = _concentration(snapshots, key_fn=_position_underlyings, total_capital=total_capital_at_risk or 0.0)
    expiration_conc = _concentration(
        snapshots, key_fn=lambda s: tuple(str(e) for e in _position_expirations(s)), total_capital=total_capital_at_risk or 0.0,
    )
    correlated_conc: dict[str, float] = {}
    if total_capital_at_risk:
        group_totals: dict[str, float] = {}
        for s in determinable:
            underlyings = _position_underlyings(s)
            if len(underlyings) != 1:
                continue
            group = correlated_groups.get(underlyings[0])
            if group is None:
                continue
            group_totals[group] = group_totals.get(group, 0.0) + s.max_loss
        correlated_conc = {g: v / total_capital_at_risk for g, v in group_totals.items()}

    results: list[RiskCheckResult] = []

    def _pct_check(code: str, limit: float | None, value: float | None, label: str) -> None:
        if limit is None:
            results.append(RiskCheckResult(code, True, f"{label}: no limit configured (NOT_CONFIGURED)"))
            return
        if value is None:
            results.append(RiskCheckResult(code, True, f"{label}: undeterminable (partial/unbounded risk) -- cannot evaluate against configured limit"))
            return
        ok = value <= limit
        results.append(RiskCheckResult(code, ok, f"{label} {value:.1%} {'within' if ok else 'EXCEEDS'} configured limit {limit:.1%}"))

    _pct_check("CAPITAL_AT_RISK", limits.max_capital_at_risk_pct, capital_pct, "Total capital at risk")

    largest_position_pct = None
    if determinable and account_equity_usd > 0:
        largest_position_pct = max(s.max_loss for s in determinable) / account_equity_usd
    _pct_check("SINGLE_POSITION_SIZE", limits.max_single_position_pct, largest_position_pct, "Largest single position")

    worst_underlying_pct = max(underlying_conc.values()) if underlying_conc else None
    _pct_check("UNDERLYING_CONCENTRATION", limits.max_single_underlying_concentration_pct, worst_underlying_pct, "Worst single-underlying concentration")

    worst_expiration_pct = max(expiration_conc.values()) if expiration_conc else None
    _pct_check("EXPIRATION_CONCENTRATION", limits.max_single_expiration_concentration_pct, worst_expiration_pct, "Worst single-expiration concentration")

    worst_correlated_pct = max(correlated_conc.values()) if correlated_conc else None
    _pct_check("CORRELATED_POSITION_CONCENTRATION", limits.max_correlated_group_concentration_pct, worst_correlated_pct, "Worst correlated-group concentration")

    # --- liquidity / spread / data quality, from the referenced ResearchObservation rows (if supplied) ---
    if limits.max_spread_pct is None:
        results.append(RiskCheckResult("SPREAD", True, "Spread: no limit configured (NOT_CONFIGURED)"))
    else:
        worst_spread = None
        for s in snapshots:
            for leg in s.legs:
                row = liquidity_by_contract.get(leg.contract_id)
                if row is None or row.bid is None or row.ask is None:
                    continue
                mid = (row.bid + row.ask) / 2
                if mid <= 0:
                    continue
                spread_pct = (row.ask - row.bid) / mid
                worst_spread = spread_pct if worst_spread is None else max(worst_spread, spread_pct)
        _pct_check("SPREAD", limits.max_spread_pct, worst_spread, "Widest referenced leg spread")

    for code, limit, field, label in (
        ("LIQUIDITY_VOLUME", limits.min_liquidity_volume, "volume", "Volume"),
        ("LIQUIDITY_OPEN_INTEREST", limits.min_liquidity_open_interest, "open_interest", "Open interest"),
    ):
        if limit is None:
            results.append(RiskCheckResult(code, True, f"{label}: no minimum configured (NOT_CONFIGURED)"))
            continue
        worst = None
        for s in snapshots:
            for leg in s.legs:
                row = liquidity_by_contract.get(leg.contract_id)
                value = getattr(row, field, None) if row is not None else None
                if value is None:
                    continue
                worst = value if worst is None else min(worst, value)
        if worst is None:
            results.append(RiskCheckResult(code, True, f"{label}: no referenced liquidity data supplied -- cannot evaluate"))
        else:
            ok = worst >= limit
            results.append(RiskCheckResult(code, ok, f"{label} {worst} {'meets' if ok else 'BELOW'} configured minimum {limit}"))

    # --- gap risk (needs caller-supplied recent-move data; never fabricated) ---
    if limits.max_recent_gap_move_pct is None:
        results.append(RiskCheckResult("GAP_RISK", True, "Gap risk: no limit configured (NOT_CONFIGURED)"))
    else:
        results.append(RiskCheckResult(
            "GAP_RISK", True,
            "Gap risk: this portfolio-level assessment does not receive recent-move data -- "
            "evaluate with src.options.research_features's underlying_momentum per-contract instead",
        ))

    # --- assignment/exercise risk: short legs ITM within the configured DTE threshold ---
    if limits.assignment_risk_dte_threshold is None:
        results.append(RiskCheckResult("ASSIGNMENT_EXERCISE_RISK", True, "Assignment/exercise risk: no DTE threshold configured (NOT_CONFIGURED)"))
    else:
        at_risk_legs = []
        for s in snapshots:
            for leg in s.legs:
                if leg.side != "short" or leg.dte is None or leg.dte > limits.assignment_risk_dte_threshold:
                    continue
                underlying_price = underlying_prices.get(leg.underlying)
                if underlying_price is None:
                    continue
                itm = (underlying_price > leg.strike) if leg.call_put == "call" else (underlying_price < leg.strike)
                if itm:
                    at_risk_legs.append(leg.contract_id)
        results.append(RiskCheckResult(
            "ASSIGNMENT_EXERCISE_RISK", len(at_risk_legs) == 0,
            "No short ITM legs within the assignment-risk DTE window" if not at_risk_legs
            else f"Short ITM leg(s) within {limits.assignment_risk_dte_threshold} DTE of expiration: {at_risk_legs}",
        ))

    # --- data quality ---
    flagged = [row.option_id for row in liquidity_by_contract.values() if row.data_quality == DataQualityStatus.FLAGGED_CRITICAL]
    if not limits.reject_on_flagged_critical_quality:
        results.append(RiskCheckResult("DATA_QUALITY", True, "Data-quality rejection disabled by configuration"))
    else:
        results.append(RiskCheckResult(
            "DATA_QUALITY", len(flagged) == 0,
            "No referenced contract carries a FLAGGED_CRITICAL data-quality flag" if not flagged
            else f"Referenced contract(s) with FLAGGED_CRITICAL data quality: {flagged}",
        ))

    return PortfolioRiskAssessment(
        account_equity_usd=account_equity_usd, position_count=len(snapshots),
        total_capital_at_risk_usd=total_capital_at_risk, capital_at_risk_is_partial=capital_partial,
        capital_at_risk_pct=capital_pct, underlying_concentration_pct=underlying_conc,
        expiration_concentration_pct=expiration_conc, correlated_group_concentration_pct=correlated_conc,
        results=tuple(results),
    )
