"""
Centralized logger factory.

Usage:

    from utils.logging_utils import get_logger
    logger = get_logger(__name__)

`configure_logging()` should be called once at process start (from your
entrypoint) to set the root level and format. After that, every
`get_logger()` call returns a child logger of the configured root.
"""
from __future__ import annotations

import sys
import logging
from typing import IO, Optional
from typing import Optional

# Process-wide flag so we only configure the root handler once.
# Lower-case name because we reassign it — Pylance treats UPPER_CASE
# module-level names as constants and rejects redefinition.
_configured: bool = False

DEFAULT_FORMAT: str = (
    "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
DEFAULT_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"


from typing import IO, Optional

def configure_logging(
    level: int = logging.INFO,
    fmt: str = DEFAULT_FORMAT,
    datefmt: str = DEFAULT_DATE_FORMAT,
    stream: Optional[IO[str]] = None,
) -> None:
    """
    Configure the root logger once. Subsequent calls are no-ops.

    Pass `stream=sys.stdout` if you prefer stdout over stderr.
    """
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))

    root = logging.getLogger()
    root.setLevel(level)

    # Remove any handlers a library may have installed (e.g. httpx's
    # default handler) so we don't get duplicate lines.
    for existing in list(root.handlers):
        root.removeHandler(existing)

    root.addHandler(handler)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger for the given name.

    If `configure_logging()` has not been called yet, the root logger
    still emits at WARNING by default — that's fine, but you'll miss
    INFO lines. Call `configure_logging()` from your entrypoint.
    """
    return logging.getLogger(name)