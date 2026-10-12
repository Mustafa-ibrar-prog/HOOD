"""TEMPORARY bisection tool, not part of the trading system -- delete
once the zoneinfo contamination source is found and fixed for real.

Problem being bisected: ZoneInfo("America/New_York") resolves fine in
a plain `python` process (confirmed on the reporting machine: Windows,
no system tz database, tzdata pip package only) but raises
ZoneInfoNotFoundError partway through a full `pytest -q` run. Since
the failure shows up widely across the suite, something that runs
EARLY in pytest's collection/execution order is almost certainly
contaminating process state (sys.modules, importlib caches, etc.) for
every test after it.

This script binary-searches pytest's default (alphabetical) file
collection order: it runs test_zzz_zoneinfo_diagnostic.py together
with just the first N test files (for a probed N), and checks whether
the diagnostic's own `ZoneInfo("America/New_York")` call still
succeeds. That turns "which of ~190 files is the culprit" into ~8
runs instead of up to 190.

Usage (from the repo root, same venv/interpreter you run pytest with):

    python scripts/bisect_zoneinfo.py

It prints progress as it narrows the range, then reports the single
file where the diagnostic flips from OK to FAILED -- that file (or
its first-N-files prefix) is where to look for the actual contaminating
import/call.

If it reports "no flip found" (diagnostic passes even with ALL files
included), the contamination isn't a function of *which* files are
collected in this simple prefix sense -- e.g. it could depend on
specific tests actually *running* (not just collecting), on test
*selection* (-k) changing order, or on something outside tests/
entirely (a plugin, conftest.py, a sitecustomize.py). Re-check by hand
at that point rather than trusting this script further.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"
DIAGNOSTIC = TESTS_DIR / "test_zzz_zoneinfo_diagnostic.py"

SUCCESS_MARKER = "ZoneInfo('America/New_York') OK"
FAILURE_MARKER = "ZoneInfo('America/New_York') FAILED"


def all_test_files() -> list[Path]:
    files = sorted(p for p in TESTS_DIR.glob("test_*.py") if p != DIAGNOSTIC)
    return files


def diagnostic_passes(prefix_files: list[Path]) -> bool:
    """Run the diagnostic alongside the given test files only. Returns
    True if ZoneInfo resolved OK, False if it failed. Raises if the
    diagnostic's own output couldn't be found at all (e.g. a collection
    error) so a bad result isn't silently misread."""
    args = [sys.executable, "-m", "pytest", *(str(f) for f in prefix_files), str(DIAGNOSTIC), "-q", "-s"]
    result = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True, timeout=600)
    output = result.stdout + result.stderr
    if SUCCESS_MARKER in output:
        return True
    if FAILURE_MARKER in output:
        return False
    print(output[-4000:])
    raise RuntimeError(
        f"Could not find either marker in pytest output for prefix of {len(prefix_files)} files -- "
        "see the tail of output printed above (likely a collection error)."
    )


def main() -> None:
    files = all_test_files()
    n = len(files)
    print(f"{n} test files found under tests/ (excluding the diagnostic itself).")

    print("Checking the diagnostic ALONE (0 other files) ...")
    if not diagnostic_passes([]):
        print("FAILED even with zero other test files collected -- the contamination isn't")
        print("about which OTHER files get collected. Look at conftest.py, plugins, or")
        print("something outside tests/ entirely (sitecustomize.py, a pytest plugin, etc).")
        return
    print("OK with zero other files, as expected.")

    print(f"Checking the diagnostic with ALL {n} other files ...")
    if diagnostic_passes(files):
        print("OK even with every other file included -- could not reproduce the failure this way.")
        print("The contamination may depend on test SELECTION/ORDER (-k, -p no:randomly, xdist)")
        print("rather than simply which files are collected. Re-check by running the real")
        print("failing test directly: pytest tests/test_hood_provider.py -q -s")
        return
    print("Confirmed: FAILED with the full set. Binary-searching for the flip point...")

    lo, hi = 0, n  # invariant: prefix of `lo` files passes, prefix of `hi` files fails
    while hi - lo > 1:
        mid = (lo + hi) // 2
        prefix = files[:mid]
        ok = diagnostic_passes(prefix)
        print(f"  prefix of {mid:3d} files -> {'OK' if ok else 'FAILED'}  (range now [{lo if ok else mid}, {hi if ok else mid}])")
        if ok:
            lo = mid
        else:
            hi = mid

    culprit = files[hi - 1]
    print()
    print(f"Flip point found: prefix of {lo} files passes, prefix of {hi} files fails.")
    print(f"Culprit file (position {hi} in alphabetical order): {culprit.relative_to(REPO_ROOT)}")
    print("Inspect that file's module-level code and fixtures for what it imports or mutates --")
    print("that's what's poisoning zoneinfo/tzdata resolution for every test after it.")


if __name__ == "__main__":
    main()
