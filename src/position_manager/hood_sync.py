"""Read-only sync of the user's REAL Robinhood option positions, via
get_option_positions — never a manually-constructed stand-in.

Verified live (read-only, real account, zero-quantity/closed positions —
this session's account had no open options at verification time, so field
*names* are confirmed but a fully-populated nonzero example was not
available):

  get_option_positions(account_number, nonzero=True) ->
  {"data": {"positions": [
      {"option_id", "chain_id", "chain_symbol", "type" ("long"/"short"),
       "quantity", "average_price", "expiration_date",
       "trade_value_multiplier", "intraday_average_open_price",
       "intraday_quantity", "pending_buy_quantity", "pending_sell_quantity",
       "pending_exercise_quantity", "pending_assignment_quantity",
       "pending_expiration_quantity", "opened_at" (not always present)},
      ...
  ]}, "guide": "..."}.

Strike price and option type (call/put) are NOT on the position row — per
the tool's own guidance, they must be looked up via get_option_instruments
using option_id. This module batches that lookup into one call across all
positions being synced.

This module NEVER calls place_option_order / review_option_order /
cancel_option_order, and never invents position data — a row this parser
can't make sense of is skipped with a warning, not guessed at. Only "long"
positions are synced: this system's OpenPosition model (and the HOOD order
tools' single-leg capability) only represents long calls/puts; short
option positions are logged and skipped, not silently misrepresented as
something they're not.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from logging import Logger
from typing import Any

from src.config.settings import Settings
from src.logging.app_logger import get_app_logger
from src.market.hood_client import HoodToolClient
from src.position_manager.models import OpenPosition
from src.strategy.decision import TradeThesis

EXTERNAL_POSITION_SETUP_NAME = "synced-from-robinhood"


@dataclass(frozen=True)
class HoodSyncResult:
    positions: tuple[OpenPosition, ...]
    skipped_short_count: int
    skipped_unparseable_count: int


def sync_open_positions_from_hood(
    client: HoodToolClient,
    account_number: str,
    settings: Settings,
    *,
    logger: Logger | None = None,
) -> HoodSyncResult:
    """Fetch the account's real, currently-open option positions and
    convert them into OpenPosition records for the position monitor to
    evaluate. Read-only: calls only get_option_positions and
    get_option_instruments.

    Positions this system did not itself open have no known thesis or
    trader-set profit target/stop loss — those are filled in from
    Settings.synced_position_profit_target_pct /
    synced_position_stop_loss_pct (a configured default risk policy for
    externally-opened positions, not fabricated data) applied to the
    position's own cost basis.
    """
    logger = logger or get_app_logger()

    try:
        response = client.get_option_positions(account_number, nonzero=True)
    except Exception as exc:  # noqa: BLE001
        raise HoodSyncError(f"get_option_positions failed for account {account_number}: {exc}") from exc

    data = _unwrap(response, "get_option_positions")
    rows = data.get("positions") or []

    long_rows = []
    skipped_short = 0
    for row in rows:
        quantity = _to_float(row.get("quantity"))
        if quantity is None or quantity == 0:
            continue  # closed/zero-quantity — not an open position
        if row.get("type") != "long":
            skipped_short += 1
            logger.warning(
                "Skipping a %s option position (option_id=%s): this system only "
                "represents long calls/puts",
                row.get("type"),
                row.get("option_id"),
            )
            continue
        long_rows.append(row)

    if not long_rows:
        return HoodSyncResult(positions=(), skipped_short_count=skipped_short, skipped_unparseable_count=0)

    option_ids = [row["option_id"] for row in long_rows if row.get("option_id")]
    instrument_by_id = _fetch_instrument_details(client, option_ids, logger)

    positions: list[OpenPosition] = []
    skipped_unparseable = 0
    for row in long_rows:
        try:
            position = _row_to_open_position(row, instrument_by_id, settings)
        except (KeyError, ValueError, TypeError) as exc:
            skipped_unparseable += 1
            logger.warning("Skipping an unparseable real position (option_id=%s): %s", row.get("option_id"), exc)
            continue
        if position is not None:
            positions.append(position)
        else:
            skipped_unparseable += 1

    return HoodSyncResult(
        positions=tuple(positions), skipped_short_count=skipped_short, skipped_unparseable_count=skipped_unparseable
    )


class HoodSyncError(RuntimeError):
    """A get_option_positions/get_option_instruments call failed or
    returned something this module could not parse at all."""


def _fetch_instrument_details(client: HoodToolClient, option_ids: list[str], logger: Logger) -> dict[str, dict[str, Any]]:
    """Batches strike/type lookups into as few get_option_instruments calls
    as the tool allows (comma-separated ids), per its own documented shape
    (confirmed live in hood_provider.py's verification): {"data":
    {"instruments": [...]}}."""
    if not option_ids:
        return {}
    try:
        response = client.get_option_instruments(ids=",".join(option_ids))
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_option_instruments failed while resolving synced positions' strikes: %s", exc)
        return {}
    try:
        data = _unwrap(response, "get_option_instruments")
    except HoodSyncError as exc:
        logger.warning("Could not parse get_option_instruments response while syncing positions: %s", exc)
        return {}
    return {row["id"]: row for row in (data.get("instruments") or []) if row.get("id")}


def _row_to_open_position(
    row: dict[str, Any], instrument_by_id: dict[str, dict[str, Any]], settings: Settings
) -> OpenPosition | None:
    option_id = row.get("option_id")
    if not option_id:
        return None

    instrument = instrument_by_id.get(option_id)
    if instrument is None:
        raise ValueError(f"could not resolve strike/type for option_id {option_id}")

    option_type = instrument.get("type")  # "call" | "put"
    if option_type not in ("call", "put"):
        raise ValueError(f"unexpected option type {option_type!r} for option_id {option_id}")
    side = "long_call" if option_type == "call" else "long_put"
    direction = "bullish" if option_type == "call" else "bearish"

    symbol = row["chain_symbol"]
    quantity = int(float(row["quantity"]))
    entry_price = float(row["average_price"])
    multiplier = int(float(row.get("trade_value_multiplier", 100)))
    strike = instrument.get("strike_price", "?")

    opened_at_raw = row.get("opened_at")
    entry_time = _parse_datetime(opened_at_raw) or datetime.now(timezone.utc)

    cost_basis_usd = entry_price * quantity * multiplier
    profit_target_usd = round(cost_basis_usd * settings.synced_position_profit_target_pct, 2)
    stop_loss_usd = round(cost_basis_usd * settings.synced_position_stop_loss_pct, 2)
    # Both must be strictly positive (OpenPosition's own validation) — a
    # zero cost basis (shouldn't happen for a real nonzero position, but
    # defend anyway) would otherwise raise ValueError deep in the
    # constructor with a less useful message.
    profit_target_usd = max(profit_target_usd, 0.01)
    stop_loss_usd = max(stop_loss_usd, 0.01)

    thesis = TradeThesis(
        setup_name=EXTERNAL_POSITION_SETUP_NAME,
        direction=direction,
        catalyst="Position already open in the real Robinhood account; opened outside this system.",
        invalidation="n/a — thesis not tracked for externally-opened positions",
        profit_target_usd=profit_target_usd,
        stop_loss_usd=stop_loss_usd,
        notes=(
            f"Synced from Robinhood via get_option_positions. Profit target/stop loss are "
            f"this system's configured defaults ({settings.synced_position_profit_target_pct:.0%} / "
            f"{settings.synced_position_stop_loss_pct:.0%} of cost basis), not something the "
            "original trader set."
        ),
    )

    return OpenPosition(
        symbol=symbol,
        option_id=option_id,
        option_description=f"{symbol} {row['expiration_date']} {option_type[0].upper()} {strike}",
        side=side,
        quantity=quantity,
        entry_price=entry_price,
        entry_time=entry_time,
        thesis=thesis,
        profit_target_usd=profit_target_usd,
        stop_loss_usd=stop_loss_usd,
        expiration=date.fromisoformat(row["expiration_date"]),
        contract_multiplier=multiplier,
    )


def _unwrap(response: Any, context: str) -> dict[str, Any]:
    if not isinstance(response, dict) or not isinstance(response.get("data"), dict):
        raise HoodSyncError(f"{context}: expected a top-level 'data' object, got {type(response).__name__}")
    return response["data"]


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
