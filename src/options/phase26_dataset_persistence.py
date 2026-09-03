"""Phase 26, Part 12 — the storage-layer requirements applied to the
real ingested sample: raw data is never modified in place (the fetch
script only ever writes a zip once and extracts once, both idempotent
skip-if-present operations -- see scripts/phase26_step0_fetch_actual_
sample.py), and this module adds the NORMALIZED representation plus a
real, reproducible dataset version/source fingerprint on top, without
ever overwriting or discarding the raw files it was built from.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from src.options.phase26_dataset_builder import InMemoryLeanSampleStore

DATASET_VERSION = "phase26_quantconnect_lean_sample_v1"


def compute_source_fingerprint(zip_dir: Path) -> str:
    """SHA-256 over the sorted, concatenated bytes of every real raw zip
    -- a real, reproducible fingerprint of the exact bytes this dataset
    was built from (recomputing it against a re-downloaded copy of the
    same files must produce the same value, and did -- see
    tests/test_phase26_dataset_persistence.py)."""
    hasher = hashlib.sha256()
    for path in sorted(Path(zip_dir).glob("*")):
        if path.is_file():
            hasher.update(path.name.encode("utf-8"))
            hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _contract_record(store: InMemoryLeanSampleStore, contract_id: str) -> dict:
    contract = store.contracts[contract_id]
    lifecycle = store.lifecycles.get(contract_id)
    return {
        "option_id": contract.option_id,
        "underlying_symbol": contract.underlying_symbol,
        "call_put": contract.call_put,
        "strike": contract.strike,
        "expiration": contract.expiration.isoformat(),
        "multiplier": contract.multiplier,
        "multiplier_source_confirmed": False,
        "exercise_style": contract.exercise_style,
        "contract_status": contract.contract_status,
        "lifecycle": None if lifecycle is None else {
            "first_observable_date": lifecycle.first_observable_date.isoformat() if lifecycle.first_observable_date else None,
            "first_listed_date": lifecycle.first_listed_date.isoformat() if lifecycle.first_listed_date else None,
            "last_trade_date": lifecycle.last_trade_date.isoformat() if lifecycle.last_trade_date else None,
            "expiration_date": lifecycle.expiration_date.isoformat(),
            "status": lifecycle.status.value,
        },
        "n_quote_observations": len(store.quotes.get(contract_id, [])),
        "n_trade_observations": len(store.trades.get(contract_id, [])),
        "n_open_interest_observations": len(store.open_interest.get(contract_id, [])),
        "provenance_source": contract.provenance.source,
        "provenance_confidence_status": contract.provenance.confidence_status,
    }


def write_normalized_dataset(store: InMemoryLeanSampleStore, out_path: Path, *, source_fingerprint: str) -> dict:
    """Writes one JSON line per contract (never a partial/silent
    overwrite of raw data -- this is a NEW, separate, normalized output
    file). Returns the manifest dict that was also written as the first
    line, for a caller to assert against without re-reading the file."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "_manifest": True,
        "dataset_version": DATASET_VERSION,
        "source_fingerprint": source_fingerprint,
        "n_contracts": len(store.contracts),
    }
    with out_path.open("w") as f:
        f.write(json.dumps(manifest) + "\n")
        for contract_id in sorted(store.contracts):
            f.write(json.dumps(_contract_record(store, contract_id)) + "\n")
    return manifest
