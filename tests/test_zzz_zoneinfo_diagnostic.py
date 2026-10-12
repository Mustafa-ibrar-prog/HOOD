"""TEMPORARY diagnostic, not a real test -- delete once the zoneinfo
root cause (works in a standalone process, fails inside a pytest run,
on a Windows machine with no system tz database, tzdata resolved
entirely via the tzdata pip package through importlib.resources) is
found and fixed for real.

Named test_zzz_* so default alphabetical collection runs it LAST,
after every other tests/test_*.py file -- the point of this file is
to capture the *pytest-process* state right now, after whatever
collection/import has already happened, and compare it against the
same checks run in a plain `python` process (see
scripts/diagnose_zoneinfo.py, which prints the identical checks).

Run with -s so the prints aren't captured, e.g.:
    pytest tests/test_hood_provider.py::test_happy_path_assembles_full_snapshot tests/test_zzz_zoneinfo_diagnostic.py -q -s
    pytest tests/test_hood_provider.py tests/test_zzz_zoneinfo_diagnostic.py -q -s
    pytest -q -s   (full suite, this file runs last)
"""

from __future__ import annotations

import importlib.resources as resources
import sys
import zoneinfo


def test_zoneinfo_process_state_diagnostic():
    print("\n--- zoneinfo diagnostic (pytest process) ---")
    print("sys.platform =", sys.platform)
    print("sys.executable =", sys.executable)
    print("zoneinfo.TZPATH =", zoneinfo.TZPATH)

    print("'tzdata' in sys.modules =", "tzdata" in sys.modules)
    print("sys.modules.get('tzdata') =", sys.modules.get("tzdata"))
    print("sys.modules.get('tzdata.zoneinfo') =", sys.modules.get("tzdata.zoneinfo"))
    print("sys.modules.get('tzdata.zoneinfo.America') =", sys.modules.get("tzdata.zoneinfo.America"))

    try:
        import tzdata
        print("tzdata.__file__ =", tzdata.__file__)
        print("tzdata.__path__ =", list(tzdata.__path__))
    except Exception as exc:
        print("import tzdata FAILED:", type(exc).__name__, exc)

    try:
        tzdata_zoneinfo = resources.files("tzdata.zoneinfo")
        print("resources.files('tzdata.zoneinfo') =", tzdata_zoneinfo)
        ny = tzdata_zoneinfo.joinpath("America").joinpath("New_York")
        print("NY path =", ny)
        print("NY exists (is_file) =", ny.is_file())
    except Exception as exc:
        print("resources.files('tzdata.zoneinfo') FAILED:", type(exc).__name__, exc)

    try:
        tzdata_america = resources.files("tzdata.zoneinfo.America")
        print("resources.files('tzdata.zoneinfo.America') =", tzdata_america)
    except Exception as exc:
        print("resources.files('tzdata.zoneinfo.America') FAILED:", type(exc).__name__, exc)

    try:
        tz = zoneinfo.ZoneInfo("America/New_York")
        print("ZoneInfo('America/New_York') OK ->", tz)
    except Exception as exc:
        print("ZoneInfo('America/New_York') FAILED:", type(exc).__name__, exc)

    print("sys.path[:8] =", sys.path[:8])
    print("--- end diagnostic ---\n")

    # Never fails on its own -- it's pure observation, run it alongside
    # the real failing test and read the printed state either way.
    assert True
