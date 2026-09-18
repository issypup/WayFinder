"""Reusable decorators for WayFinder."""
from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from .error_handler import ErrorHandler

P = ParamSpec("P")
R = TypeVar("R")


def handle_errors(
    user_message: str,
    error_title: str = "Error",
    show_dialog: bool = True,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Route exceptions from a callable through :class:`ErrorHandler`.

    The original exception is always re-raised so callers and tests retain the
    existing failure semantics; the decorator only centralizes logging/UI.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        """Handle decorator."""
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            """Handle wrapper."""
            try:
                return func(*args, **kwargs)
            except Exception as error:
                ErrorHandler().handle_error(
                    error,
                    user_message,
                    error_title,
                    log_exception=True,
                    show_dialog=show_dialog,
                )
                raise

        return wrapper

    return decorator
