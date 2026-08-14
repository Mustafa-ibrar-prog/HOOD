"""Application and decision logging.

NAMING CAUTION: this package is named `logging`, same as the Python
standard library module. That is safe as long as it is only ever imported
by its full dotted path — `import src.logging` / `from src.logging import
...` — and the `src/` directory itself is never added directly to
sys.path (only the project root, which contains `src/` as a package,
should be on sys.path). This project's pyproject.toml pytest config and
README follow that rule. Do not add `sys.path.insert(0, "src")` anywhere,
or bare `import logging` elsewhere in this codebase will resolve to this
package instead of the standard library.
"""

from __future__ import annotations

from src.logging.app_logger import get_app_logger
from src.logging.decision_logger import DecisionLogger

__all__ = ["get_app_logger", "DecisionLogger"]
