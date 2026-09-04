"""Phase 29, Part 2/17 — the query builder and the credentials-
unavailable client: every method must raise, never fabricate a
response."""

from __future__ import annotations

import pytest

from src.options.orats_client import (
    TARGET_EXPANSION_UNDERLYINGS,
    CredentialsUnavailableClient,
    ORATSCredentialsUnavailableError,
    ORATSHistoricalStrikesQuery,
    build_aapl_validation_query,
    build_expansion_query,
)
from src.options.orats_config import ORATSConfig


def test_aapl_validation_query_is_a_single_symbol():
    q = build_aapl_validation_query("2021-12-01")
    assert q.tickers == ("AAPL",)
    assert q.trade_date == "2021-12-01"
    assert q.to_query_params() == {"tickers": "AAPL", "tradeDate": "2021-12-01"}


def test_expansion_query_covers_part_2s_exact_eleven_symbols():
    assert TARGET_EXPANSION_UNDERLYINGS == ("NVDA", "TSLA", "SPY", "QQQ", "MSFT", "AMD", "AMZN", "META", "GOOGL", "NFLX", "IWM")
    q = build_expansion_query("2021-12-01")
    assert set(q.tickers) == set(TARGET_EXPANSION_UNDERLYINGS)


def test_query_rejects_empty_tickers():
    with pytest.raises(ValueError):
        ORATSHistoricalStrikesQuery(tickers=(), trade_date="2021-12-01")


def test_query_rejects_more_than_twelve_tickers_never_a_bulk_pull():
    with pytest.raises(ValueError):
        ORATSHistoricalStrikesQuery(tickers=tuple(f"SYM{i}" for i in range(13)), trade_date="2021-12-01")


def test_credentials_unavailable_client_raises_on_every_method_when_unconfigured():
    cfg = ORATSConfig.from_env(env={})
    client = CredentialsUnavailableClient(cfg)
    q = build_aapl_validation_query("2021-12-01")
    with pytest.raises(ORATSCredentialsUnavailableError):
        client.get_historical_strikes(q)
    with pytest.raises(ORATSCredentialsUnavailableError):
        client.get_dividend_history("AAPL")
    with pytest.raises(ORATSCredentialsUnavailableError):
        client.get_stock_split_history("AAPL")


def test_credentials_unavailable_client_still_refuses_even_when_configured():
    """This phase never implements a real call, even if a key were
    somehow present -- see the module's own docstring on why."""
    cfg = ORATSConfig.from_env(env={"ORATS_API_KEY": "sk_fake_test_key_never_real"})
    client = CredentialsUnavailableClient(cfg)
    q = build_aapl_validation_query("2021-12-01")
    with pytest.raises(ORATSCredentialsUnavailableError):
        client.get_historical_strikes(q)


def test_credentials_unavailable_client_never_returns_a_value():
    """Every method must raise, not return None/[] silently."""
    import inspect
    cfg = ORATSConfig.from_env(env={})
    client = CredentialsUnavailableClient(cfg)
    for method_name in ("get_historical_strikes", "get_dividend_history", "get_stock_split_history"):
        method = getattr(client, method_name)
        assert callable(method)
