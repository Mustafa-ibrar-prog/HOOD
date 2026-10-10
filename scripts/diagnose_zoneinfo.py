"""TEMPORARY diagnostic, not part of the trading system -- delete once
the zoneinfo root cause is found. Prints the exact same checks as
tests/test_zzz_zoneinfo_diagnostic.py, but in a plain `python` process,
so the two outputs can be diffed directly:

    python scripts/diagnose_zoneinfo.py
    pytest tests/test_hood_provider.py::test_happy_path_assembles_full_snapshot tests/test_zzz_zoneinfo_diagnostic.py -q -s
"""

from __future__ import annotations

import importlib.resources as resources
import sys
import zoneinfo


def main() -> None:
    print("--- zoneinfo diagnostic (plain python process) ---")
    print("sys.platform =", sys.platform)
    print("sys.executable =", sys.executable)
    print("zoneinfo.TZPATH =", zoneinfo.TZPATH)

    print("'tzdata' in sys.modules =", "tzdata" in sys.modules)

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
    print("--- end diagnostic ---")


if __name__ == "__main__":
    main()
