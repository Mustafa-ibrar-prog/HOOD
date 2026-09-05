"""Phase 37, Part 10 — quote quality validation.

Never deletes or silently drops an observation. Every check below
attaches an explicit flag to the (unchanged) `NormalizedOptionObservation`
-- a future researcher decides what to do with a flagged row, this
module never decides for them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.research_recorder.normalized_observation import NormalizedOptionObservation

DEFAULT_EXTREME_SPREAD_PCT = 0.50  # a broad, disclosed observation-time flag, NOT a trading threshold (Part 11)
DEFAULT_STALE_QUOTE_SECONDS = 90.0


class QualityFlag(str, Enum):
    MISSING_BID = "MISSING_BID"
    MISSING_ASK = "MISSING_ASK"
    BID_NOT_POSITIVE = "BID_NOT_POSITIVE"
    ASK_NOT_POSITIVE = "ASK_NOT_POSITIVE"
    CROSSED_MARKET = "CROSSED_MARKET"  # ask < bid
    EXTREME_SPREAD = "EXTREME_SPREAD"
    STALE_TIMESTAMP = "STALE_TIMESTAMP"
    DUPLICATE_OBSERVATION = "DUPLICATE_OBSERVATION"
    MALFORMED_CONTRACT = "MALFORMED_CONTRACT"  # missing option_id/underlying/strike/expiration/option_type
    EXPIRED_CONTRACT = "EXPIRED_CONTRACT"  # dte < 0
    INACTIVE_CONTRACT = "INACTIVE_CONTRACT"  # contract_state present and != "active"


@dataclass(frozen=True)
class QualityAssessment:
    option_id: str
    flags: tuple[QualityFlag, ...]

    @property
    def is_clean(self) -> bool:
        return not self.flags


def assess_quote_quality(
    observation: NormalizedOptionObservation, *, now: datetime, max_quote_age_seconds: float = DEFAULT_STALE_QUOTE_SECONDS,
    extreme_spread_pct: float = DEFAULT_EXTREME_SPREAD_PCT, is_duplicate: bool = False,
) -> QualityAssessment:
    flags: list[QualityFlag] = []

    if observation.option_id is None or observation.underlying is None or observation.strike is None \
            or observation.expiration is None or observation.option_type is None:
        flags.append(QualityFlag.MALFORMED_CONTRACT)

    if observation.bid is None:
        flags.append(QualityFlag.MISSING_BID)
    elif observation.bid <= 0:
        flags.append(QualityFlag.BID_NOT_POSITIVE)

    if observation.ask is None:
        flags.append(QualityFlag.MISSING_ASK)
    elif observation.ask <= 0:
        flags.append(QualityFlag.ASK_NOT_POSITIVE)

    if observation.bid is not None and observation.ask is not None:
        if observation.ask < observation.bid:
            flags.append(QualityFlag.CROSSED_MARKET)
        elif observation.midpoint is not None and observation.midpoint > 0:
            spread_pct = (observation.ask - observation.bid) / observation.midpoint
            if spread_pct > extreme_spread_pct:
                flags.append(QualityFlag.EXTREME_SPREAD)

    if observation.market_timestamp is not None:
        age = (now - observation.market_timestamp).total_seconds()
        if age > max_quote_age_seconds:
            flags.append(QualityFlag.STALE_TIMESTAMP)

    if observation.dte is not None and observation.dte < 0:
        flags.append(QualityFlag.EXPIRED_CONTRACT)

    if observation.contract_state is not None and observation.contract_state != "active":
        flags.append(QualityFlag.INACTIVE_CONTRACT)

    if is_duplicate:
        flags.append(QualityFlag.DUPLICATE_OBSERVATION)

    return QualityAssessment(option_id=observation.option_id, flags=tuple(flags))
