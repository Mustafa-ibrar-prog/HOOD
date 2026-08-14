"""Account/permissions verification, required to pass BEFORE the very first
live order is ever proposed.

This module parses already-fetched get_accounts / get_portfolio responses
(agent-mediated — see live_client.py's docstring on why nothing here calls
those tools itself) and answers one question: is it currently safe for this
account to have a live order proposed against it at all? It does not know
anything about a specific candidate trade — RiskManager still separately
gates every individual order's size/spread/liquidity/etc.

Deliberately conservative: any field that's missing, unparsable, or not
exactly the expected value is treated as a FAILING check, never skipped or
assumed-good. A preflight that silently passes on ambiguous data defeats the
entire point of a preflight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    account_number: str
    checks: tuple[str, ...] = field(default_factory=tuple)  # human-readable, one per check performed
    failures: tuple[str, ...] = field(default_factory=tuple)
    buying_power_usd: float | None = None

    def require_ok(self) -> None:
        if not self.ok:
            raise PreflightFailedError(
                f"Live-trading preflight failed for account {self.account_number}: "
                f"{'; '.join(self.failures)}"
            )


class PreflightFailedError(RuntimeError):
    """Raised by PreflightResult.require_ok() — callers that must not
    proceed without a passing preflight should call that rather than
    inspecting `.ok` themselves, so a forgotten check can't silently let a
    failing account through."""


_ALLOWED_OPTION_LEVELS = {"option_level_2", "option_level_3"}


def _find_account(accounts_response: Mapping[str, Any], account_number: str) -> Mapping[str, Any] | None:
    """get_accounts' exact response shape has not been independently
    verified live (see live_client.py), so this looks for the account under
    either a top-level "results" list (the shape every other HOOD list
    endpoint in this codebase uses — see hood_provider.py) or, defensively,
    a bare top-level list, matching on "account_number"."""
    candidates: Any = accounts_response.get("results", accounts_response.get("accounts"))
    if candidates is None and isinstance(accounts_response, list):
        candidates = accounts_response
    if not isinstance(candidates, list):
        return None
    for row in candidates:
        if isinstance(row, Mapping) and str(row.get("account_number")) == str(account_number):
            return row
    return None


def _extract_buying_power(portfolio_response: Mapping[str, Any] | None) -> float | None:
    if not portfolio_response:
        return None
    for key in ("buying_power", "options_buying_power", "option_buying_power"):
        raw = portfolio_response.get(key)
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                continue
    return None


def verify_account_preflight(
    *,
    accounts_response: Mapping[str, Any],
    portfolio_response: Mapping[str, Any] | None,
    account_number: str,
    max_position_size_usd: float,
) -> PreflightResult:
    """Verify one account is safe to propose live orders against right now.

    Every individual check is recorded (pass or fail) in `checks`/
    `failures` so a human reviewing this before approving the first live
    trade can see exactly what was verified, not just a bare True/False.
    """
    checks: list[str] = []
    failures: list[str] = []

    account = _find_account(accounts_response, account_number)
    if account is None:
        failures.append(f"account {account_number!r} not found in get_accounts response")
        return PreflightResult(
            ok=False,
            account_number=account_number,
            checks=tuple(checks),
            failures=tuple(failures),
        )
    checks.append(f"account {account_number!r} found in get_accounts")

    agentic_allowed = account.get("agentic_allowed")
    if agentic_allowed is True:
        checks.append("agentic_allowed=true")
    else:
        failures.append(f"agentic_allowed is {agentic_allowed!r}, not true")

    option_level = account.get("option_level")
    if option_level in _ALLOWED_OPTION_LEVELS:
        checks.append(f"option_level={option_level!r} permits options trading")
    else:
        failures.append(f"option_level is {option_level!r}, not one of {sorted(_ALLOWED_OPTION_LEVELS)}")

    # Defensive: some account states (deactivated, restricted, closed) may
    # surface as an explicit flag rather than just an absent permission —
    # check for the obvious ones without assuming a single canonical field
    # name, since this shape hasn't been independently verified live.
    for deactivation_key in ("deactivated", "is_deactivated", "closed"):
        if account.get(deactivation_key) is True:
            failures.append(f"account field {deactivation_key!r} is true")
    state = account.get("state")
    if state is not None and str(state).lower() not in {"active", "approved"}:
        failures.append(f"account state is {state!r}, not active")
    if state is not None and str(state).lower() in {"active", "approved"}:
        checks.append(f"account state={state!r}")

    buying_power = _extract_buying_power(portfolio_response)
    if buying_power is None:
        failures.append("could not determine buying power from get_portfolio response")
    else:
        checks.append(f"buying_power_usd={buying_power:.2f}")
        if buying_power < max_position_size_usd:
            failures.append(
                f"buying_power_usd={buying_power:.2f} is less than "
                f"MAX_POSITION_SIZE_USD={max_position_size_usd:.2f} — cannot safely size even one position"
            )

    return PreflightResult(
        ok=not failures,
        account_number=account_number,
        checks=tuple(checks),
        failures=tuple(failures),
        buying_power_usd=buying_power,
    )
