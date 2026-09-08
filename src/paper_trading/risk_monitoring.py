"""Phase 40, Part 20 — risk monitoring during the experiment.

Every threshold here is explicit and configurable (Part 20: "Do NOT
create arbitrary conservative restrictions. All limits must be explicit
and configurable") — passed in by the caller (from `ExperimentConfig.
risk_configuration` or a default), never a hard-coded magic number
buried in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class RiskMonitoringSnapshot:
    max_position_exposure_usd: float  # the single largest open position's market value
    portfolio_exposure_usd: float  # sum of all open positions' market value
    portfolio_exposure_pct_of_equity: float
    concentration_by_symbol: Mapping[str, float]  # symbol -> fraction of portfolio_exposure_usd
    max_observed_loss_usd: float  # the worst single closed trade's net_pnl_usd (0 if none negative / no closed trades)
    current_drawdown_pct: float
    cash_utilization_pct: float  # 1 - (cash / equity)
    illiquid_open_positions: tuple[str, ...]  # option_ids currently below the caller-supplied liquidity thresholds
    wide_spread_open_positions: tuple[str, ...]  # option_ids currently above the caller-supplied max spread_pct
    stale_quote_positions: tuple[str, ...]  # option_ids whose last real quote is older than the caller-supplied max age


def compute_risk_monitoring_snapshot(
    *,
    open_position_market_values: Mapping[str, float],  # option_id -> current market value
    open_position_symbols: Mapping[str, str],  # option_id -> underlying symbol
    equity_usd: float,
    cash_usd: float,
    current_drawdown_pct: float,
    closed_trade_net_pnls: Sequence[float],
    liquidity_flags: Mapping[str, bool],  # option_id -> True if illiquid per RiskLimits-derived thresholds
    spread_flags: Mapping[str, bool],  # option_id -> True if spread exceeds the configured max
    stale_flags: Mapping[str, bool],  # option_id -> True if quote age exceeds the configured max
) -> RiskMonitoringSnapshot:
    portfolio_exposure = sum(open_position_market_values.values())
    max_exposure = max(open_position_market_values.values(), default=0.0)

    concentration: dict[str, float] = {}
    if portfolio_exposure > 0:
        by_symbol: dict[str, float] = {}
        for option_id, value in open_position_market_values.items():
            symbol = open_position_symbols.get(option_id, "?")
            by_symbol[symbol] = by_symbol.get(symbol, 0.0) + value
        concentration = {symbol: value / portfolio_exposure for symbol, value in by_symbol.items()}

    max_loss = min((p for p in closed_trade_net_pnls if p < 0), default=0.0)
    cash_utilization = (1 - (cash_usd / equity_usd)) if equity_usd > 0 else 0.0

    return RiskMonitoringSnapshot(
        max_position_exposure_usd=round(max_exposure, 2), portfolio_exposure_usd=round(portfolio_exposure, 2),
        portfolio_exposure_pct_of_equity=(portfolio_exposure / equity_usd) if equity_usd > 0 else 0.0,
        concentration_by_symbol=concentration, max_observed_loss_usd=round(max_loss, 2),
        current_drawdown_pct=current_drawdown_pct, cash_utilization_pct=cash_utilization,
        illiquid_open_positions=tuple(oid for oid, flag in liquidity_flags.items() if flag),
        wide_spread_open_positions=tuple(oid for oid, flag in spread_flags.items() if flag),
        stale_quote_positions=tuple(oid for oid, flag in stale_flags.items() if flag),
    )
