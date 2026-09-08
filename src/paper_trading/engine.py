"""Phase 40, Part 9/22 — the per-cycle autonomous experiment wrapper.

Does NOT reimplement the decision pipeline. Every cycle:

  1. `src.research_recorder.recorder.run_observation_cycle` (Phase 37,
     UNCHANGED) — real data, MARKET_CLOSED handling, provenance,
     observation_cycle_id. If it returns MARKET_CLOSED, this function
     returns immediately (no paper decision this cycle — Part 22).
  2. `src.orchestrator.run_trading_cycle` (UNCHANGED) — the real,
     already-complete autonomous paper engine (scan -> risk -> simulated
     entry via PaperExecutionGateway -> position monitoring ->
     deterministic exits -> TradeJournal). The ONLY thing this wrapper
     does before calling it is override THREE `Settings` fields via
     `dataclasses.replace` (never mutating the shared/global Settings):
     `scan_universe` (the experiment's own universe), `max_position_
     size_usd` (capped at the experiment account's REAL remaining cash —
     Part 14's "position sizing... must determine how many contracts can
     actually be purchased," enforced by reusing `RiskManager.
     check_position_size` completely unchanged rather than adding a
     parallel capital check), and the experiment-specific file paths (so
     a 14-day experiment never shares state with, or collides with, the
     general-purpose bot's own paper-trading files).
  3. Cross-references the resulting `CycleReport.new_entries`/`exits`
     against Phase 37's real normalized-option data (same cycle) and the
     experiment-local `PaperPositionStore`/`TradeJournal` to build the
     enriched `PaperExperimentTradeRecord`(s) (Part 19) and the equity
     snapshot (Part 17) — read-only cross-referencing, never a second
     decision.

Never imports `src.execution.gateway` or `src.execution.live_client`
directly — everything execution-adjacent is reached only through
`src.orchestrator.run_trading_cycle`'s own (already-audited, paper-only-
in-this-package) call graph. See tests/test_phase40_safety.py.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from src.config.constants import CONTRACT_MULTIPLIER
from src.config.settings import Settings
from src.orchestrator import run_trading_cycle
from src.paper_trading.account import PaperExperimentAccountSnapshot, compute_account_snapshot
from src.paper_trading.equity_curve import EquitySnapshotStore, build_equity_snapshot
from src.paper_trading.experiment_config import ExperimentConfig
from src.paper_trading.journal import (
    PAPER_EXPERIMENT_LABEL,
    PaperExperimentTradeRecord,
    PaperExperimentTradeStore,
    deterministic_trade_id,
)
from src.paper_trading.slippage import (
    NO_EXECUTABLE_QUOTE,
    SlippageAssumptionTier,
    compute_cost_breakdown,
    entry_execution_price,
    exit_execution_price,
)
from src.position_manager.store import PaperPositionStore
from src.research_recorder.recorder import MARKET_CLOSED, RecorderStores, run_observation_cycle

if TYPE_CHECKING:
    from src.market.data_provider import MarketDataProvider
    from src.market.hood_client import HoodToolClient

MARKET_CLOSED_RESULT = "MARKET_CLOSED"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
NO_QUALIFIED_OPPORTUNITY = "NO_QUALIFIED_OPPORTUNITY"
INSUFFICIENT_PAPER_CAPITAL = "INSUFFICIENT_PAPER_CAPITAL"
UNSUPPORTED_STRUCTURE = "UNSUPPORTED_STRUCTURE"
CYCLE_OK = "CYCLE_OK"

_SUPPORTED_STRUCTURES = frozenset({"long_call", "long_put"})


@dataclass(frozen=True)
class ExperimentPaths:
    base_dir: Path
    paper_positions_file: Path
    risk_state_file: Path
    trade_journal_file: Path  # the EXISTING, general-shape TradeJournal (reused, not replaced)
    decision_log_file: Path
    app_log_file: Path
    peak_prices_file: Path
    pending_orders_file: Path
    live_bot_positions_file: Path
    experiment_config_file: Path
    experiment_state_file: Path
    experiment_trades_file: Path  # Phase 40's own enriched PaperExperimentTradeRecord store
    equity_curve_file: Path
    research_recorder_dir: Path  # Phase 37 stores, dedicated per experiment (never the shared research/logs/research_data/phase37 path -- an experiment's own data provenance is self-contained)


def experiment_paths(experiment_id: str, base_dir: Path = Path("logs/paper_experiments")) -> ExperimentPaths:
    root = Path(base_dir) / experiment_id
    return ExperimentPaths(
        base_dir=root,
        paper_positions_file=root / "paper_positions.json",
        risk_state_file=root / "risk_state.json",
        trade_journal_file=root / "trade_journal.jsonl",
        decision_log_file=root / "decisions.jsonl",
        app_log_file=root / "app.log",
        peak_prices_file=root / "peak_prices.json",
        pending_orders_file=root / "pending_orders.json",
        live_bot_positions_file=root / "live_bot_positions.json",
        experiment_config_file=root / "experiment_config.json",
        experiment_state_file=root / "experiment_state.jsonl",
        experiment_trades_file=root / "experiment_trades.jsonl",
        equity_curve_file=root / "equity_curve.jsonl",
        research_recorder_dir=root / "research_recorder",
    )


def build_experiment_settings(
    *, base_settings: Settings, config: ExperimentConfig, paths: ExperimentPaths, available_cash_usd: float,
) -> Settings:
    """Never mutates `base_settings` (frozen dataclass) — returns a NEW
    Settings with ONLY the fields an experiment must control overridden.
    `max_position_size_usd` is capped by REAL remaining cash, enforced
    downstream by the completely-unmodified `RiskManager.check_position_
    size` — this is Part 14's capital-affordability gate, built by
    configuring the existing check, not by adding a parallel one."""
    ceiling_fraction = config.risk_configuration.get("max_position_size_fraction_of_equity", 1.0)
    ceiling = config.starting_capital_usd * float(ceiling_fraction)
    max_position_size = max(0.0, min(available_cash_usd, ceiling))
    return dataclasses.replace(
        base_settings,
        scan_universe=config.universe,
        max_position_size_usd=max_position_size if max_position_size > 0 else 0.01,  # Settings validates > 0; 0.01 with 0 cash structurally blocks every entry via check_position_size anyway
        paper_positions_file=str(paths.paper_positions_file),
        risk_state_file=str(paths.risk_state_file),
        trade_journal_file=str(paths.trade_journal_file),
        decision_log_file=str(paths.decision_log_file),
        app_log_file=str(paths.app_log_file),
        peak_prices_file=str(paths.peak_prices_file),
        pending_orders_file=str(paths.pending_orders_file),
        live_bot_positions_file=str(paths.live_bot_positions_file),
        # Deliberately NOT overridden: emergency_stop_file, system_state_log_file,
        # account_number -- these stay the SAME real, global files/value so this
        # experiment is checked against (and can never diverge from) the real
        # emergency-stop/authorization state (Part 30).
    )


@dataclass(frozen=True)
class PaperExperimentCycleResult:
    outcome: str  # one of MARKET_CLOSED_RESULT / DATA_UNAVAILABLE / NO_QUALIFIED_OPPORTUNITY / CYCLE_OK
    observation_cycle_id: str | None
    new_trades: tuple[PaperExperimentTradeRecord, ...]
    closed_trades: tuple[PaperExperimentTradeRecord, ...]
    account_snapshot: PaperExperimentAccountSnapshot | None
    errors: tuple[str, ...]
    unsupported_structures: tuple[str, ...]  # option_ids of any candidate whose side wasn't long_call/long_put -- structurally unreachable for this frozen strategy, checked anyway (Part 8)


def run_paper_experiment_cycle(
    *,
    config: ExperimentConfig,
    client: "HoodToolClient",
    market: "MarketDataProvider",
    base_settings: Settings,
    now: datetime | None = None,
    slippage_tier: SlippageAssumptionTier = SlippageAssumptionTier.BASELINE,
    paths: ExperimentPaths | None = None,
) -> PaperExperimentCycleResult:
    now = now or datetime.now(timezone.utc)
    paths = paths or experiment_paths(config.experiment_id)
    paths.base_dir.mkdir(parents=True, exist_ok=True)

    from src.research_recorder.storage import (
        CycleLogStore,
        NormalizedOptionStore,
        NormalizedUnderlyingStore,
        RawObservationStore,
        ResearchSignalStore,
    )

    recorder_stores = RecorderStores(
        raw=RawObservationStore(paths.research_recorder_dir / "raw_observations.jsonl"),
        underlying=NormalizedUnderlyingStore(paths.research_recorder_dir / "normalized_underlying.jsonl"),
        option=NormalizedOptionStore(paths.research_recorder_dir / "normalized_options.jsonl"),
        signal=ResearchSignalStore(paths.research_recorder_dir / "research_signals.jsonl"),
        cycle_log=CycleLogStore(paths.research_recorder_dir / "cycle_log.jsonl"),
    )

    observation_result = run_observation_cycle(
        client=client, market=market, settings=base_settings, stores=recorder_stores, now=now, universe=config.universe,
    )
    if observation_result == MARKET_CLOSED:
        return PaperExperimentCycleResult(
            outcome=MARKET_CLOSED_RESULT, observation_cycle_id=None, new_trades=(), closed_trades=(),
            account_snapshot=None, errors=(), unsupported_structures=(),
        )
    observation_cycle_id = observation_result.observation_cycle_id

    trade_store = PaperExperimentTradeStore(paths.experiment_trades_file)
    closed_before = {t.trade_id for t in trade_store.load_all() if t.exit_timestamp is not None}

    paper_store = PaperPositionStore(paths.paper_positions_file)
    open_positions_before = {p.option_id for p in paper_store.load()}

    from src.logging.trade_journal import TradeJournal

    journal = TradeJournal(paths.trade_journal_file)
    journal_entries_before = len(journal.load())

    account_before = _load_or_zero_snapshot(paths, config, now)
    settings_for_cycle = build_experiment_settings(
        base_settings=base_settings, config=config, paths=paths, available_cash_usd=account_before.cash_usd,
    )

    cycle_report = run_trading_cycle(settings=settings_for_cycle, market_data=market, hood_client=client, now=now)

    errors = tuple(cycle_report.errors)
    if not cycle_report.ran:
        # Orchestrator's own market-hours/account-number gate -- should be
        # rare given the recorder above already confirmed the market is
        # open, but account_number missing is a real, distinct reason.
        return PaperExperimentCycleResult(
            outcome=MARKET_CLOSED_RESULT if "market hours" in (cycle_report.skipped_reason or "") else DATA_UNAVAILABLE,
            observation_cycle_id=observation_cycle_id, new_trades=(), closed_trades=(), account_snapshot=None,
            errors=(cycle_report.skipped_reason or "",), unsupported_structures=(),
        )

    option_rows_by_id = _latest_option_rows(recorder_stores.option, observation_cycle_id)

    # --- New entries this cycle -------------------------------------------------------
    new_records: list[PaperExperimentTradeRecord] = []
    unsupported: list[str] = []
    open_positions = paper_store.load()
    for position in open_positions:
        if position.option_id not in open_positions_before:
            if position.side not in _SUPPORTED_STRUCTURES:
                unsupported.append(position.option_id)  # structurally unreachable given OpenPosition.__post_init__ already rejects this, but checked explicitly (Part 8)
                continue
            row = option_rows_by_id.get(position.option_id)
            entry_priced = entry_execution_price(
                bid=row.get("bid") if row else None, ask=row.get("ask") if row else None, tier=slippage_tier,
            )
            trade_id = deterministic_trade_id(
                experiment_id=config.experiment_id, option_id=position.option_id, entry_observation_cycle_id=observation_cycle_id,
            )
            record = PaperExperimentTradeRecord(
                label=PAPER_EXPERIMENT_LABEL, experiment_id=config.experiment_id, trade_id=trade_id,
                strategy_id=config.strategy_id, strategy_content_hash=config.strategy_content_hash,
                entry_observation_cycle_id=observation_cycle_id, exit_observation_cycle_id=None,
                entry_timestamp=position.entry_time, exit_timestamp=None, symbol=position.symbol,
                option_id=position.option_id, strike=row.get("strike") if row else None,
                expiration=position.expiration, option_type=row.get("option_type") if row else None,
                dte_at_entry=row.get("dte") if row else None, moneyness_at_entry=row.get("moneyness") if row else None,
                entry_bid=row.get("bid") if row else None, entry_ask=row.get("ask") if row else None,
                entry_fill=position.entry_price,  # the REAL simulated fill from PaperExecutionGateway
                exit_bid=None, exit_ask=None, exit_fill=None, quantity=position.quantity,
                gross_pnl_usd=None, spread_cost_usd=None, slippage_usd=None, fees_usd=None, net_pnl_usd=None,
                return_pct=None, mfe_pct=None, mae_pct=None, exit_reason=None,
                slippage_tier=slippage_tier.value,
            )
            trade_store.append(record)
            new_records.append(record)

    # --- Exits this cycle ---------------------------------------------------------------
    closed_records: list[PaperExperimentTradeRecord] = []
    new_journal_entries = journal.load()[journal_entries_before:]
    for exited_option_id in cycle_report.exits:
        matching_open = next((r for r in trade_store.load_all() if r.option_id == exited_option_id and r.exit_timestamp is None), None)
        journal_entry = next((e for e in new_journal_entries if e.option_id == exited_option_id), None)
        if matching_open is None:
            continue  # a real (non-paper) position exit -- not part of this experiment's own ledger
        row = option_rows_by_id.get(exited_option_id)
        exit_bid = row.get("bid") if row else None
        exit_ask = row.get("ask") if row else None

        # The REAL, zero-slippage fill run_trading_cycle's PaperExecutionGateway
        # actually produced, recovered algebraically from the EXISTING
        # TradeJournalEntry's own realized_pnl_usd (the same
        # entry_price + pnl/(qty*multiplier) formula src.orchestrator._realized_pnl
        # already uses to derive that pnl in the first place -- reused, not
        # reinvented) -- authoritative, never a second independent fill.
        exit_fill_real = None
        gross = spread_cost = slippage_cost = fees = net = mfe = mae = None
        if journal_entry is not None:
            exit_fill_real = round(
                matching_open.entry_fill + journal_entry.realized_pnl_usd / (matching_open.quantity * CONTRACT_MULTIPLIER), 4,
            )
            gross = round(journal_entry.realized_pnl_usd, 2)  # the REAL fill's own gross P&L -- authoritative

        entry_priced = entry_execution_price(bid=matching_open.entry_bid, ask=matching_open.entry_ask, tier=slippage_tier)
        exit_priced = exit_execution_price(bid=exit_bid, ask=exit_ask, tier=slippage_tier)
        if entry_priced != NO_EXECUTABLE_QUOTE and exit_priced != NO_EXECUTABLE_QUOTE:
            breakdown = compute_cost_breakdown(entry=entry_priced, exit=exit_priced, quantity=matching_open.quantity)
            spread_cost, slippage_cost, fees = breakdown.spread_cost_usd, breakdown.slippage_usd, breakdown.fees_usd
            if gross is None:
                gross = breakdown.gross_pnl_usd  # fallback if no journal entry matched (should not happen in practice)
            net = round(gross - slippage_cost - fees, 2)
            mfe, mae = _compute_mfe_mae(
                recorder_stores.option, option_id=exited_option_id, entry_fill=matching_open.entry_fill,
                entry_time=matching_open.entry_timestamp, exit_time=now,
            )

        updated = dataclasses.replace(
            matching_open, exit_observation_cycle_id=observation_cycle_id, exit_timestamp=now,
            exit_bid=exit_bid, exit_ask=exit_ask, exit_fill=exit_fill_real,
            gross_pnl_usd=gross, spread_cost_usd=spread_cost, slippage_usd=slippage_cost, fees_usd=fees, net_pnl_usd=net,
            return_pct=(net / (matching_open.entry_fill * matching_open.quantity * CONTRACT_MULTIPLIER)) if net is not None and matching_open.entry_fill else None,
            mfe_pct=mfe, mae_pct=mae, exit_reason=journal_entry.exit_reason if journal_entry else "unknown",
        )
        trade_store.append(updated)
        closed_records.append(updated)

    # --- Account snapshot + equity curve --------------------------------------------------
    all_trades = trade_store.load_all()
    closed_trades = [t for t in all_trades if t.exit_timestamp is not None]
    current_bid_by_option_id = {oid: row["bid"] for oid, row in option_rows_by_id.items() if row.get("bid") is not None}
    equity_store = EquitySnapshotStore(paths.equity_curve_file)
    running_peak = equity_store.running_peak_equity()
    snapshot = compute_account_snapshot(
        as_of=now, starting_cash_usd=config.starting_capital_usd, closed_trades=closed_trades,
        open_positions=paper_store.load(), current_bid_by_option_id=current_bid_by_option_id,
        historical_peak_equity_usd=running_peak,
    )
    first_today = equity_store.first_equity_on_date(now.date())
    equity_record = build_equity_snapshot(
        experiment_id=config.experiment_id, observation_cycle_id=observation_cycle_id, snapshot=snapshot,
        first_snapshot_equity_today=first_today,
    )
    equity_store.append(equity_record)

    outcome = CYCLE_OK if (new_records or closed_records) else NO_QUALIFIED_OPPORTUNITY
    return PaperExperimentCycleResult(
        outcome=outcome, observation_cycle_id=observation_cycle_id, new_trades=tuple(new_records),
        closed_trades=tuple(closed_records), account_snapshot=snapshot, errors=errors,
        unsupported_structures=tuple(unsupported),
    )


def _load_or_zero_snapshot(paths: ExperimentPaths, config: ExperimentConfig, now: datetime) -> PaperExperimentAccountSnapshot:
    equity_store = EquitySnapshotStore(paths.equity_curve_file)
    latest = equity_store.latest()
    if latest is not None:
        return PaperExperimentAccountSnapshot(
            as_of=latest.timestamp, starting_cash_usd=config.starting_capital_usd, cash_usd=latest.cash_usd,
            open_position_market_value_usd=latest.market_value_usd, equity_usd=latest.equity_usd,
            realized_pnl_usd=latest.realized_pnl_usd, unrealized_pnl_usd=latest.unrealized_pnl_usd,
            total_return_pct=(latest.equity_usd - config.starting_capital_usd) / config.starting_capital_usd,
            peak_equity_usd=latest.peak_equity_usd, max_drawdown_pct=latest.drawdown_pct,
            current_drawdown_pct=latest.drawdown_pct, open_position_count=latest.open_positions,
            positions_missing_a_current_quote=(),
        )
    return PaperExperimentAccountSnapshot(
        as_of=now, starting_cash_usd=config.starting_capital_usd, cash_usd=config.starting_capital_usd,
        open_position_market_value_usd=0.0, equity_usd=config.starting_capital_usd, realized_pnl_usd=0.0,
        unrealized_pnl_usd=0.0, total_return_pct=0.0, peak_equity_usd=config.starting_capital_usd,
        max_drawdown_pct=0.0, current_drawdown_pct=0.0, open_position_count=0, positions_missing_a_current_quote=(),
    )


def _latest_option_rows(option_store, observation_cycle_id: str) -> dict[str, dict]:
    rows = option_store.load_all_raw_dicts()
    return {r["option_id"]: r for r in rows if r["observation_cycle_id"] == observation_cycle_id}


def _compute_mfe_mae(option_store, *, option_id: str, entry_fill: float, entry_time: datetime, exit_time: datetime) -> tuple[float | None, float | None]:
    """Best/worst MID-based unrealized excursion vs entry_fill, over every
    real observation of this contract recorded strictly between entry and
    exit (inclusive) -- the same mid-based MFE/MAE convention Phase 38's
    ForwardOutcome already established for research, applied here to a
    real, closed experiment position rather than a hypothetical research
    outcome. Returns (None, None) if no real observation carries both a
    real bid and ask in the window (never fabricated)."""
    rows = option_store.load_all_raw_dicts()
    mids: list[float] = []
    for r in rows:
        if r.get("option_id") != option_id:
            continue
        ts = datetime.fromisoformat(r["observation_timestamp"])
        if ts < entry_time or ts > exit_time:
            continue
        bid, ask = r.get("bid"), r.get("ask")
        if bid is not None and ask is not None:
            mids.append((bid + ask) / 2)
    if not mids or entry_fill in (None, 0):
        return None, None
    excursions = [(m - entry_fill) / entry_fill for m in mids]
    return max(excursions), min(excursions)
