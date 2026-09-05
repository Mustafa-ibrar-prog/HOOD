"""Phase 37, Part 8 — immutable raw observation preservation.

Every observation preserves the RAW tool response (before any
transformation) alongside its retrieval metadata. `RawObservation` is a
frozen dataclass; nothing in this package ever mutates one after
construction, and `RawObservationStore` (storage.py) is append-only, so
"never overwrite historical observations" holds at both the object and
the storage layer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

SCHEMA_VERSION = "phase37-raw-v1"
PARSER_VERSION = "phase37-parser-v1"


def fingerprint_payload(raw_payload: Mapping[str, Any]) -> str:
    """A deterministic hash over the raw payload -- used to detect an
    identical re-fetch (Part 20: 'detect the duplicate rather than
    silently creating conflicting records'). Sorted-key JSON so field
    order never affects the hash."""
    blob = json.dumps(raw_payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RawObservation:
    observation_cycle_id: str
    provider: str  # e.g. "robinhood_hood_mcp"
    tool_name: str  # e.g. "get_option_quotes"
    retrieval_timestamp: datetime  # when THIS call actually returned -- never backdated to the cycle start
    market_timestamp: datetime | None  # the tool's own as-of timestamp, if it supplied one -- None if not
    raw_payload: Mapping[str, Any]
    payload_fingerprint: str
    schema_version: str = SCHEMA_VERSION
    parser_version: str = PARSER_VERSION
    request_context: Mapping[str, Any] | None = None  # e.g. {"symbol": "AAPL"} or {"option_id": "..."} -- never a credential

    def __post_init__(self) -> None:
        if self.request_context is None:
            object.__setattr__(self, "request_context", {})
        expected = fingerprint_payload(self.raw_payload)
        if self.payload_fingerprint != expected:
            raise ValueError(
                f"payload_fingerprint {self.payload_fingerprint!r} does not match the raw_payload "
                f"provided (expected {expected!r}) -- never construct a RawObservation with a "
                "stale or mismatched fingerprint."
            )

    @classmethod
    def build(
        cls, *, observation_cycle_id: str, provider: str, tool_name: str, retrieval_timestamp: datetime,
        market_timestamp: datetime | None, raw_payload: Mapping[str, Any], request_context: Mapping[str, Any] | None = None,
    ) -> "RawObservation":
        """The normal construction path -- computes the fingerprint for
        the caller so it can never drift from the actual payload."""
        return cls(
            observation_cycle_id=observation_cycle_id, provider=provider, tool_name=tool_name,
            retrieval_timestamp=retrieval_timestamp, market_timestamp=market_timestamp, raw_payload=raw_payload,
            payload_fingerprint=fingerprint_payload(raw_payload), request_context=request_context or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_cycle_id": self.observation_cycle_id, "provider": self.provider, "tool_name": self.tool_name,
            "retrieval_timestamp": self.retrieval_timestamp.isoformat(),
            "market_timestamp": self.market_timestamp.isoformat() if self.market_timestamp else None,
            "raw_payload": dict(self.raw_payload), "payload_fingerprint": self.payload_fingerprint,
            "schema_version": self.schema_version, "parser_version": self.parser_version,
            "request_context": dict(self.request_context),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RawObservation":
        return cls(
            observation_cycle_id=data["observation_cycle_id"], provider=data["provider"], tool_name=data["tool_name"],
            retrieval_timestamp=datetime.fromisoformat(data["retrieval_timestamp"]),
            market_timestamp=datetime.fromisoformat(data["market_timestamp"]) if data.get("market_timestamp") else None,
            raw_payload=data["raw_payload"], payload_fingerprint=data["payload_fingerprint"],
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            parser_version=data.get("parser_version", PARSER_VERSION),
            request_context=data.get("request_context", {}),
        )
