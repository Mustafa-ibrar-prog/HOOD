"""Phase 27, Part 11 — a combined, deterministic SHA-256 fingerprint
spanning multiple raw-zip directories (Phase 26's + Phase 27's), so the
manifest's fingerprint covers the ENTIRE real dataset actually used, not
just the newest addition. Reuses Phase 26's per-directory hashing
function rather than reimplementing it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.options.phase26_dataset_persistence import compute_source_fingerprint


def compute_combined_fingerprint(zip_dirs: list[Path]) -> str:
    """Deterministic regardless of the order `zip_dirs` is passed in --
    each directory's own fingerprint (already order-independent within
    itself) is combined by hashing the SORTED list of per-directory
    fingerprints, not the raw directory order."""
    per_dir = sorted(compute_source_fingerprint(Path(d)) for d in zip_dirs)
    hasher = hashlib.sha256()
    for fp in per_dir:
        hasher.update(fp.encode("utf-8"))
    return hasher.hexdigest()
