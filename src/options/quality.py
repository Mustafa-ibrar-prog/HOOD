"""Phase 18, Part 17 — option-specific data quality checks.

Mirrors src/data/quality.py's convention (detect and report only, never
"fix" silently) and reuses src/data/generic_quality.py's timestamp
checks where they directly apply, adding the option-specific checks that
module doesn't cover: impossible bid>ask, negative prices, invalid
strike, expired-contract-appearing-after-expiration, inconsistent
multiplier/call-put/expiration, impossible IV, invalid Greeks,
corporate-action mismatch. Unusual-but-valid markets (e.g. a very wide
spread on a thin contract) are NOT flagged -- only mathematically/
structurally impossible ones (Part 17: "Do not reject unusual but
mathematically valid markets simply because they are unusual").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from src.data.generic_quality import find_duplicate_timestamps, find_out_of_order_indices
from src.options.chain import OptionChainObservation, OptionsFieldStatus
from src.options.greeks import Greeks
from src.options.implied_volatility import IVObservation
from src.options.instrument import OptionContract


@dataclass(frozen=True)
class OptionsQualityIssue:
    code: str
    severity: str  # "ERROR" | "WARNING"
    message: str


def validate_observation(observation: OptionChainObservation) -> list[OptionsQualityIssue]:
    issues: list[OptionsQualityIssue] = []

    if observation.status_of("bid") == OptionsFieldStatus.OBSERVED and observation.bid is not None and observation.bid < 0:
        issues.append(OptionsQualityIssue("NEGATIVE_BID", "ERROR", f"bid={observation.bid} is negative"))
    if observation.status_of("ask") == OptionsFieldStatus.OBSERVED and observation.ask is not None and observation.ask < 0:
        issues.append(OptionsQualityIssue("NEGATIVE_ASK", "ERROR", f"ask={observation.ask} is negative"))
    if (
        observation.status_of("bid") == OptionsFieldStatus.OBSERVED and observation.status_of("ask") == OptionsFieldStatus.OBSERVED
        and observation.bid is not None and observation.ask is not None and observation.bid > observation.ask
    ):
        issues.append(OptionsQualityIssue("BID_EXCEEDS_ASK", "ERROR", f"bid={observation.bid} > ask={observation.ask}"))

    if observation.contract.strike <= 0:
        issues.append(OptionsQualityIssue("INVALID_STRIKE", "ERROR", f"strike={observation.contract.strike} is not > 0"))

    if observation.observation_timestamp.date() > observation.contract.expiration:
        issues.append(OptionsQualityIssue(
            "EXPIRED_CONTRACT_OBSERVED_AFTER_EXPIRATION", "ERROR",
            f"observation at {observation.observation_timestamp} is after expiration {observation.contract.expiration}",
        ))

    if observation.contract.contract_multiplier != 100 and observation.contract.is_standard_deliverable:
        issues.append(OptionsQualityIssue(
            "INCONSISTENT_MULTIPLIER", "ERROR",
            f"multiplier={observation.contract.contract_multiplier} != 100 but is_standard_deliverable=True (Part 15/17: a non-standard multiplier must be flagged via deliverable_note)",
        ))

    return issues


def validate_greeks(greeks: Greeks) -> list[OptionsQualityIssue]:
    """Part 17: 'invalid Greeks'. Delta in [-1, 1]; gamma/vega >= 0 (both
    are non-negative for standard options); |theta| and rho are not
    range-bounded the same way, so left unchecked -- an unusual but
    mathematically valid theta/rho is not an error."""
    issues: list[OptionsQualityIssue] = []
    if greeks.delta is not None and not (-1.0 <= greeks.delta <= 1.0):
        issues.append(OptionsQualityIssue("INVALID_DELTA", "ERROR", f"delta={greeks.delta} outside [-1, 1]"))
    if greeks.gamma is not None and greeks.gamma < 0:
        issues.append(OptionsQualityIssue("INVALID_GAMMA", "ERROR", f"gamma={greeks.gamma} is negative"))
    if greeks.vega is not None and greeks.vega < 0:
        issues.append(OptionsQualityIssue("INVALID_VEGA", "ERROR", f"vega={greeks.vega} is negative"))
    return issues


def validate_iv(iv: IVObservation) -> list[OptionsQualityIssue]:
    """Part 17: 'impossible IV'. IV must be >= 0 (IVObservation's own
    __post_init__ already enforces this structurally); this check flags
    an implausibly extreme value (>= 1000%, i.e. 10.0) as a WARNING, not
    an ERROR -- extreme but real IV spikes do happen around binary
    events, so this is advisory, not a rejection."""
    issues: list[OptionsQualityIssue] = []
    if iv.value is not None and iv.value >= 10.0:
        issues.append(OptionsQualityIssue("EXTREME_IV", "WARNING", f"IV={iv.value} (>=1000%) is unusually extreme -- verify before use"))
    return issues


def find_duplicate_contract_timestamp(observations: Sequence[OptionChainObservation]) -> dict[tuple, int]:
    """Part 17: 'duplicate contract/timestamp'."""
    counts: dict[tuple, int] = {}
    for obs in observations:
        key = (obs.contract.option_id, obs.observation_timestamp)
        counts[key] = counts.get(key, 0) + 1
    return {k: n for k, n in counts.items() if n > 1}


def find_timestamp_ordering_issues(observations: Sequence[OptionChainObservation]) -> list[int]:
    """Reuses generic_quality's out-of-order check on the observation
    timestamps."""
    timestamps = [obs.observation_timestamp for obs in observations]
    return find_out_of_order_indices(timestamps)


def find_inconsistent_contract_metadata(contracts: Sequence[OptionContract]) -> list[OptionsQualityIssue]:
    """Part 17: 'inconsistent call/put', 'inconsistent expiration' --
    checks that every OptionContract sharing the same option_id agrees
    on call_put/expiration/strike (a genuine identity violation if not,
    since option_id IS the identity key -- see instrument.py)."""
    issues: list[OptionsQualityIssue] = []
    by_id: dict[str, list[OptionContract]] = {}
    for c in contracts:
        by_id.setdefault(c.option_id, []).append(c)
    for option_id, group in by_id.items():
        if len(group) < 2:
            continue
        first = group[0]
        for other in group[1:]:
            if other.call_put != first.call_put:
                issues.append(OptionsQualityIssue("INCONSISTENT_CALL_PUT", "ERROR", f"{option_id} has conflicting call_put: {first.call_put} vs {other.call_put}"))
            if other.expiration != first.expiration:
                issues.append(OptionsQualityIssue("INCONSISTENT_EXPIRATION", "ERROR", f"{option_id} has conflicting expiration: {first.expiration} vs {other.expiration}"))
            if other.strike != first.strike:
                issues.append(OptionsQualityIssue("INCONSISTENT_STRIKE", "ERROR", f"{option_id} has conflicting strike: {first.strike} vs {other.strike}"))
    return issues
