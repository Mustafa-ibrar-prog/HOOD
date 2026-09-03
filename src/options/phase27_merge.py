"""Phase 27, Part 7 — a provider-neutral dataset merge layer.

Built after this phase found a REAL bug its own ordering check
(`phase26_quality_rules.check_timestamp_ordering`) surfaced: combining
QuantConnect/Lean's real DAILY GOOG quote file with its real MINUTE GOOG
quote files for the same contract (both real, both from the SAME
provider) produced 118 out-of-order flags -- not because the SOURCE data
was wrong, but because this codebase's own directory-processing order
(daily rows appended before minute rows) interleaved a contract's daily
placeholder-midnight rows for LATER real dates ahead of its minute rows
for EARLIER real dates. That is exactly the class of bug Part 7 exists
to prevent: "deterministic normalization... never silently overwrite
conflicting observations." The fix is not a patch to Phase 26's already-
certified `phase26_ingest.py` (left untouched, per Part 1's "do not
rewrite working components unnecessarily") -- it is this dedicated merge
step, which every Phase 27 multi-directory/multi-resolution/multi-source
combination must go through.

Source precedence (documented, per Part 7's explicit requirement):
every observation this phase actually merges comes from exactly ONE
real provider (QuantConnect/Lean) -- so no cross-PROVIDER precedence
question actually arose with real data this phase. The mechanism below
is nonetheless built and tested generically (including with explicit
SYNTHETIC_TEST_DATA fixtures, Part 4's required label, NEVER merged into
the real dataset) because Part 7 requires the capability to exist before
a second real provider is ever added, not after.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.data.store_interfaces import ProvenancedObservation

# Precedence is BY SOURCE STRING, most-preferred first. Real dataset this
# phase: only "quantconnect_lean_open_source_sample" ever appears, so this
# list currently has one real entry -- a future second provider must be
# added here explicitly, never inferred.
SOURCE_PRECEDENCE: tuple[str, ...] = ("quantconnect_lean_open_source_sample",)


@dataclass(frozen=True)
class MergeConflict:
    """Two DIFFERENT real values observed for the exact same
    (contract, field, timestamp) key, from different underlying
    directory loads. Part 7: 'DO NOT choose the better-looking value.
    Record the conflict.' Both source observations are preserved in the
    merged output (see `merge_observation_lists`) -- this record exists
    purely so nothing is silently lost."""

    key: str
    field: str
    event_time: object  # datetime, kept loosely typed to avoid a second import cycle
    values: tuple[object, ...]
    sources: tuple[str, ...]


def merge_observation_lists(*lists: list[ProvenancedObservation]) -> tuple[list[ProvenancedObservation], list[MergeConflict]]:
    """Deterministically merges any number of real observation lists
    (regardless of which directory/resolution they came from) into ONE
    time-ordered list per (key, field), plus an explicit conflict log.

    Determinism: output is always sorted by (key, event_time, field,
    source) -- independent of the order the input lists were passed in
    (tested explicitly). Nothing is deduplicated away silently: an exact
    duplicate (same key/field/event_time/value/source) is dropped (it is
    the SAME real observation seen twice, not new information); a
    same-key/field/event_time observation with a DIFFERING value is
    NEVER dropped -- both are kept in the output and also recorded as a
    `MergeConflict`.
    """
    all_obs: list[ProvenancedObservation] = [o for lst in lists for o in lst]

    # Exact-duplicate removal (identical on every field that matters) —
    # never removes a genuine disagreement, only a literal re-observation.
    seen = set()
    deduped: list[ProvenancedObservation] = []
    for o in all_obs:
        sig = (o.key, o.field, o.timestamps.event_time, o.value, o.source)
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append(o)

    # Conflict detection: same (key, field, event_time), different value.
    groups: dict[tuple, list[ProvenancedObservation]] = {}
    for o in deduped:
        groups.setdefault((o.key, o.field, o.timestamps.event_time), []).append(o)

    conflicts: list[MergeConflict] = []
    for (key, field, ts), group in groups.items():
        distinct_values = {o.value for o in group}
        if len(distinct_values) > 1:
            conflicts.append(MergeConflict(
                key=key, field=field, event_time=ts,
                values=tuple(o.value for o in group), sources=tuple(o.source for o in group),
            ))

    def _sort_key(o: ProvenancedObservation):
        ts = o.timestamps.event_time
        return (o.key, ts is None, ts, o.field, o.source)

    merged_sorted = sorted(deduped, key=_sort_key)
    return merged_sorted, conflicts


def merged_quotes_by_contract(*quote_dicts: dict[str, list[ProvenancedObservation]]) -> tuple[dict[str, list[ProvenancedObservation]], list[MergeConflict]]:
    """Applies `merge_observation_lists` per contract across any number
    of `{contract_id: [observations]}` dicts (e.g. one per loaded
    directory) -- this is the function Phase 27's ingestion actually
    calls to combine daily+minute (or any future multi-source) data for
    the same contract without reproducing the ordering bug this phase
    found."""
    all_keys = set()
    for d in quote_dicts:
        all_keys.update(d.keys())

    out: dict[str, list[ProvenancedObservation]] = {}
    all_conflicts: list[MergeConflict] = []
    for key in all_keys:
        lists = [d.get(key, []) for d in quote_dicts]
        merged, conflicts = merge_observation_lists(*lists)
        out[key] = merged
        all_conflicts.extend(conflicts)
    return out, all_conflicts
