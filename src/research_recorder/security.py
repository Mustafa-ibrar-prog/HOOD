"""Phase 37, Part 23 — never log or persist a credential/secret.

This recorder never handles a broker credential directly (it calls the
same injected `HoodToolClient`/`MarketDataProvider` every other
read-only module in this codebase uses — the MCP tool-call boundary
itself holds whatever auth it needs, outside this Python process, per
`src/market/hood_client.py`'s own module docstring). This module exists
as a defense-in-depth text-redaction helper for any free-text
log/diagnostic string this package emits (e.g. an exception message that
might otherwise echo a request's raw context), so a credential-shaped
substring can never survive into a log line or a research record.
"""

from __future__ import annotations

import re

_CREDENTIAL_KEY_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|auth(?:orization)?[_-]?token|secret|password)\s*[:=]\s*\S+"
)
# "Authorization: Bearer <token>" / bare "Bearer <token>" -- a distinct
# shape from the key[:=]value pattern above (space-, not colon/equals-,
# separated).
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+\S+")


def redact(text: str) -> str:
    """Replaces any credential-shaped substring with a fixed placeholder.
    Conservative by design (redacts the whole match, never tries to
    partially mask) -- this is a safety net, not a precise secret
    scanner."""
    text = _CREDENTIAL_KEY_PATTERN.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    text = _BEARER_PATTERN.sub("Bearer [REDACTED]", text)
    return text


def assert_no_credential_shaped_content(text: str) -> None:
    if _CREDENTIAL_KEY_PATTERN.search(text) or _BEARER_PATTERN.search(text):
        raise ValueError("Refusing to log/persist text that looks like it contains a credential.")
