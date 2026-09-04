"""Phase 29, Path A Step 2 / Part 17 — ORATS auth config: env-var
loading, and credential-safety (masked key, never a bare-value repr
leak in anything meant to be logged)."""

from __future__ import annotations

from src.options.orats_config import ORATSConfig


def test_unconfigured_when_no_env_var():
    cfg = ORATSConfig.from_env(env={})
    assert cfg.is_configured is False
    assert cfg.masked_key == "<not configured>"


def test_configured_when_api_key_env_var_present():
    cfg = ORATSConfig.from_env(env={"ORATS_API_KEY": "sk_live_abcdef123456"})
    assert cfg.is_configured is True


def test_empty_string_env_var_is_not_configured():
    cfg = ORATSConfig.from_env(env={"ORATS_API_KEY": "   "})
    assert cfg.is_configured is False


def test_default_base_url_is_a_real_orats_domain():
    cfg = ORATSConfig.from_env(env={})
    assert "orats" in cfg.base_url


def test_base_url_overridable_via_env():
    cfg = ORATSConfig.from_env(env={"ORATS_BASE_URL": "https://example-override.test"})
    assert cfg.base_url == "https://example-override.test"


def test_masked_key_never_reveals_the_real_key():
    real_key = "sk_live_supersecretvalue123456"
    cfg = ORATSConfig.from_env(env={"ORATS_API_KEY": real_key})
    assert real_key not in cfg.masked_key
    assert cfg.masked_key.startswith("sk")
    assert cfg.masked_key.endswith("56")
    assert "*" in cfg.masked_key


def test_masked_key_handles_a_short_key_without_crashing():
    cfg = ORATSConfig.from_env(env={"ORATS_API_KEY": "abc"})
    assert cfg.masked_key == "***"


def test_config_is_frozen():
    import dataclasses
    cfg = ORATSConfig.from_env(env={})
    assert dataclasses.is_dataclass(cfg)
    with_frozen = cfg.__dataclass_fields__
    assert "api_key" in with_frozen
