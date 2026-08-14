"""General-purpose diagnostic logging (startup, errors, connectivity),
separate from the structured decision audit trail in decision_logger.py.

Uses the Python standard library `logging` module. See src/logging/
__init__.py for why the bare `import logging` below is safe here.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_configured_loggers: dict[str, logging.Logger] = {}

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def get_app_logger(name: str = "hood_trader", log_file: str | Path | None = None) -> logging.Logger:
    """Returns a configured stdlib Logger with a console handler and,
    if log_file is given, a rotating file handler. Idempotent — calling
    this twice with the same name does not duplicate handlers."""
    if name in _configured_loggers:
        return _configured_loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(_LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    _configured_loggers[name] = logger
    return logger
