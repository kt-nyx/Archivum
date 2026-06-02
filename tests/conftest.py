"""Pytest hooks: reduce Prefect subprocess-server logging noise at interpreter exit."""

from __future__ import annotations

import atexit
import logging
import os

# Do not read a developer `.env` during tests unless `WOW_LORE_DOTENV=1` is set in the environment.
if "WOW_LORE_DOTENV" not in os.environ:
    os.environ["WOW_LORE_DOTENV"] = "0"

# Never reach the live wiki redirect API during tests unless a test explicitly opts in
# (resolver/annotation helpers are still unit-tested directly with a mocked HTTP seam).
if "WOW_LORE_INGEST_RESOLVE_REDIRECTS" not in os.environ:
    os.environ["WOW_LORE_INGEST_RESOLVE_REDIRECTS"] = "0"


def pytest_configure(config) -> None:  # noqa: ARG001
    # Quieter Prefect defaults for the test process (before first Prefect import).
    os.environ.setdefault("PREFECT_LOGGING_INTERNAL_LEVEL", "ERROR")
    os.environ.setdefault("PREFECT_LOGGING_LEVEL", "WARNING")


def _silence_prefect_logging() -> None:
    """Detach Prefect loggers so shutdown cannot write to a closed Rich console/stderr."""
    for name in list(logging.Logger.manager.loggerDict):
        if not isinstance(name, str) or not name.startswith("prefect"):
            continue
        log = logging.getLogger(name)
        for handler in list(log.handlers):
            log.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
        log.disabled = True
        log.propagate = False
        log.setLevel(logging.CRITICAL + 1)


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    # Register last so this runs first at interpreter exit (atexit LIFO), before Prefect's own
    # subprocess server teardown tries to emit INFO to a Rich console bound to closed streams.
    atexit.register(_silence_prefect_logging)
