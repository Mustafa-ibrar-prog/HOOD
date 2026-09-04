"""Phase 29, Path A Step 2 — ORATS authentication configuration.

Mirrors `src/config/settings.py`'s env-var-loading pattern (`_get_str`/
`_get_optional_str`, an immutable frozen dataclass, a `from_env()`
classmethod) without touching that file -- this is a deliberately
SEPARATE config object, not a new field on `Settings`, so this phase's
work stays additive and never risks the live-trading config surface.

CREDENTIAL SAFETY (Part 17's explicit requirement, enforced by
`tests/test_phase29_orats_config.py` and `test_phase29_safety.py`):
  - No default value for the API key is ever a real-looking string --
    the only default is `None`.
  - `ORATSConfig` never implements `__repr__`/`__str__` in a way that
    would print the key (dataclass default repr DOES include field
    values -- see `is_configured`/`masked_key` below, which is what
    logging/reporting code must use instead of the raw dataclass repr).
  - Nothing in this module, or anywhere else in this phase, ever writes
    an API key to a file, prints it, or hard-codes one as a literal.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


def _get_optional_str(env: Mapping[str, str], key: str) -> str | None:
    raw = env.get(key)
    if raw is None:
        return None
    raw = raw.strip()
    return raw or None


def _load_dotenv_into_environ(path: Path) -> None:
    """Identical convention to settings.py's own loader -- a real
    environment variable always takes precedence over a .env file."""
    if not path.is_file():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class ORATSConfig:
    api_key: str | None
    base_url: str

    @property
    def is_configured(self) -> bool:
        return self.api_key is not None and len(self.api_key) > 0

    @property
    def masked_key(self) -> str:
        """Safe to log/print/persist -- never the real key. Use this,
        never `self.api_key`, anywhere a value might reach a log file,
        a print statement, or a committed report."""
        if not self.is_configured:
            return "<not configured>"
        key = self.api_key
        if len(key) <= 4:
            return "*" * len(key)
        return key[:2] + "*" * (len(key) - 4) + key[-2:]

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, dotenv_path: Path | None = None) -> "ORATSConfig":
        if env is None:
            _load_dotenv_into_environ(dotenv_path or Path(".env"))
            env = os.environ
        return cls(
            api_key=_get_optional_str(env, "ORATS_API_KEY"),
            base_url=env.get("ORATS_BASE_URL", "https://api.orats.io/datav2").strip() or "https://api.orats.io/datav2",
        )
