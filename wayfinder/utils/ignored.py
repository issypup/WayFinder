"""Helpers for explicitly documented, low-severity ignored operations."""
from __future__ import annotations

import logging
import sys

_LOGGER = logging.getLogger("wayfinder")


def ignored(reason: str) -> None:
    """Record an intentional no-op instead of silently swallowing it.

    If called from an exception handler, the active exception is included at
    DEBUG level.  This keeps best-effort cleanup/fallback paths non-fatal while
    still making the failure diagnosable.
    """
    has_exception = sys.exc_info()[0] is not None
    _LOGGER.debug("Ignored operation: %s", reason, exc_info=has_exception)
