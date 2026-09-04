"""Phase 29, Part 2 — the ORATS historical query interface.

Defines the REQUEST shape (a real, date-scoped `/strikes` query, using
the confirmed real `tradeDate` parameter -- Phase 25's evidence) and an
abstract client Protocol, plus the ONLY concrete implementation this
phase ever constructs: `CredentialsUnavailableClient`, which raises a
clear, specific error on every method rather than returning anything --
never a fabricated empty response, never a silently-skipped call. No
other concrete client exists in this codebase (Path A: "STOP before any
real ORATS API call requiring credentials").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from src.options.orats_config import ORATSConfig


class ORATSCredentialsUnavailableError(RuntimeError):
    """Raised by every method of CredentialsUnavailableClient. Never
    caught-and-substituted with a fabricated response anywhere in this
    codebase."""


@dataclass(frozen=True)
class ORATSHistoricalStrikesQuery:
    """The real request shape for ORATS's `/hist/strikes` endpoint
    (Phase 25: DataHistoryApiRequest requires one of `tickers` or
    `trade_date`; the `/hist/` URL-prefix convention marks the
    historical variant of `/strikes`). Part 2's explicit instruction:
    'Do NOT request an enormous dataset initially... first perform a
    small validation sample' -- `tickers` defaults to a single symbol,
    never a bulk multi-symbol pull, and `trade_date` scopes to exactly
    one real historical date."""

    tickers: tuple[str, ...]
    trade_date: str  # "YYYY-MM-DD", the real confirmed query parameter

    def __post_init__(self) -> None:
        if not self.tickers:
            raise ValueError("tickers must be non-empty")
        if len(self.tickers) > 12:
            raise ValueError(
                f"got {len(self.tickers)} tickers -- Part 2 requires starting with a small validation sample, "
                "not the full target universe at once"
            )

    def to_query_params(self) -> dict[str, str]:
        return {"tickers": ",".join(self.tickers), "tradeDate": self.trade_date}


def build_aapl_validation_query(trade_date: str) -> ORATSHistoricalStrikesQuery:
    """Part 2's preferred first test: AAPL, one real historical date
    inside ORATS's documented range (reported since-2007; never
    independently confirmed any phase -- see docs/phase29_....md)."""
    return ORATSHistoricalStrikesQuery(tickers=("AAPL",), trade_date=trade_date)


# Part 2's expansion list, in order -- "only include symbols for which
# actual data is returned" (never assumed all 11 will succeed).
TARGET_EXPANSION_UNDERLYINGS: tuple[str, ...] = (
    "NVDA", "TSLA", "SPY", "QQQ", "MSFT", "AMD", "AMZN", "META", "GOOGL", "NFLX", "IWM",
)


def build_expansion_query(trade_date: str, underlyings: tuple[str, ...] = TARGET_EXPANSION_UNDERLYINGS) -> ORATSHistoricalStrikesQuery:
    return ORATSHistoricalStrikesQuery(tickers=underlyings, trade_date=trade_date)


@runtime_checkable
class ORATSHistoricalClient(Protocol):
    """The real shape any future concrete client (built only once real
    credentials exist) must implement."""

    def get_historical_strikes(self, query: ORATSHistoricalStrikesQuery) -> list[dict]: ...
    def get_dividend_history(self, ticker: str) -> list[dict]: ...
    def get_stock_split_history(self, ticker: str) -> list[dict]: ...


class CredentialsUnavailableClient:
    """The only concrete ORATSHistoricalClient this phase constructs.
    Every method raises -- never returns a value, fabricated or
    otherwise. Constructing this class itself is always safe (no
    network call, no credential read beyond the config object's own
    is_configured check)."""

    def __init__(self, config: ORATSConfig) -> None:
        self._config = config

    def _refuse(self, method: str) -> None:
        if self._config.is_configured:
            # Path B would apply here in a future phase with a real client --
            # this class is deliberately never upgraded to make a real call.
            raise ORATSCredentialsUnavailableError(
                f"{method}() was called on CredentialsUnavailableClient even though ORATSConfig.is_configured is "
                f"True -- this phase never implements a real API call; a future phase must build and use a real "
                f"client class instead of calling this one"
            )
        raise ORATSCredentialsUnavailableError(
            f"{method}() cannot proceed -- no ORATS_API_KEY is configured. Per Phase 29 Path A: build the "
            f"adapter and STOP before any real API call requiring credentials. Final state: "
            f"ORATS_ACTIVATION_PENDING_HUMAN."
        )

    def get_historical_strikes(self, query: ORATSHistoricalStrikesQuery) -> list[dict]:
        self._refuse("get_historical_strikes")

    def get_dividend_history(self, ticker: str) -> list[dict]:
        self._refuse("get_dividend_history")

    def get_stock_split_history(self, ticker: str) -> list[dict]:
        self._refuse("get_stock_split_history")
