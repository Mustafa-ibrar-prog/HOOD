"""Phase 32, Part 1/21 — preregistered bucket definitions.

Reuses Phase 19's `src.options.expiration.{DTEBucket,bucket_dte}` and
`src.options.moneyness.{MoneynessBucket,classify_moneyness}` directly —
their bucket edges (DTE: 0-7/8-30/31-60/61-120/120+; moneyness:
deep_itm/itm/near_atm/otm/deep_otm) are EXACTLY the taxonomy this
phase's prompt itself suggests, chosen before any Phase 19 discovery
result was seen (per that module's own docstring) — not re-derived here.
Phase 31's `phase31_panel_builder.py` already tags every contract-day
row with `dte_bucket`/`moneyness_bucket` computed from these exact
functions, so this module's FINE scheme is "whatever Phase 31 already
computed," not a new classifier.

Per Part 1's explicit instruction ("do NOT hard-code these exact buckets
if the free dataset's actual density makes them statistically
unusable... preregister a small set of reasonable bucket definitions,
measure bucket density, use only buckets meeting explicit minimum-
observation requirements"), TWO schemes are preregistered BEFORE density
is measured: FINE (the full 5x5 taxonomy above) and COARSE (a merged
3x3 fallback -- ITM-side collapsed to one bucket, OTM-side collapsed to
one bucket, near_atm kept distinct; short/medium DTE collapsed, long DTE
kept distinct). `select_scheme_by_density` (in `phase32_density_audit.py`)
is what actually decides which one a real run uses, and documents the
choice.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.options.expiration import DTEBucket
from src.options.moneyness import MoneynessBucket

DTE_BUCKET_VALUES_FINE: tuple[str, ...] = tuple(b.value for b in DTEBucket if b != DTEBucket.EXPIRED)
MONEYNESS_BUCKET_VALUES_FINE: tuple[str, ...] = tuple(b.value for b in MoneynessBucket)

# COARSE fallback merge maps -- preregistered alongside FINE, before any
# density number was seen.
_COARSE_DTE_MERGE: dict[str, str] = {
    "0-7": "short", "8-30": "short",
    "31-60": "medium", "61-120": "medium",
    "120+": "long",
}
_COARSE_MONEYNESS_MERGE: dict[str, str] = {
    "deep_itm": "itm_side", "itm": "itm_side",
    "near_atm": "near_atm",
    "otm": "otm_side", "deep_otm": "otm_side",
}
DTE_BUCKET_VALUES_COARSE: tuple[str, ...] = ("short", "medium", "long")
MONEYNESS_BUCKET_VALUES_COARSE: tuple[str, ...] = ("itm_side", "near_atm", "otm_side")


@dataclass(frozen=True)
class BucketScheme:
    name: str  # "fine" | "coarse"
    dte_values: tuple[str, ...]
    moneyness_values: tuple[str, ...]

    def coarsen_dte(self, fine_dte_bucket: str | None) -> str | None:
        if fine_dte_bucket is None:
            return None
        if self.name == "fine":
            return fine_dte_bucket if fine_dte_bucket in self.dte_values else None
        return _COARSE_DTE_MERGE.get(fine_dte_bucket)

    def coarsen_moneyness(self, fine_moneyness_bucket: str | None) -> str | None:
        if fine_moneyness_bucket is None:
            return None
        if self.name == "fine":
            return fine_moneyness_bucket if fine_moneyness_bucket in self.moneyness_values else None
        return _COARSE_MONEYNESS_MERGE.get(fine_moneyness_bucket)


FINE_SCHEME = BucketScheme(name="fine", dte_values=DTE_BUCKET_VALUES_FINE, moneyness_values=MONEYNESS_BUCKET_VALUES_FINE)
COARSE_SCHEME = BucketScheme(name="coarse", dte_values=DTE_BUCKET_VALUES_COARSE, moneyness_values=MONEYNESS_BUCKET_VALUES_COARSE)
PREREGISTERED_SCHEMES: tuple[BucketScheme, ...] = (FINE_SCHEME, COARSE_SCHEME)
