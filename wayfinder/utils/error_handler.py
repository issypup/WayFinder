"""Centralized GUI-safe error handling for WayFinder."""
from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Optional

_LOGGER = logging.getLogger("wayfinder")

try:
    # Keep compatibility with a future/shared exception hierarchy without making
    # this utility depend on a module that is not present in the current tree.
    from .exceptions import WayFinderException  # type: ignore
except ImportError:  # pragma: no cover - compatibility path
    class WayFinderException(Exception):
        """Fallback base exception until the shared exception module exists."""


class ErrorHandler:
    """Singleton responsible for logging and user-facing error dialogs."""

    _instance: Optional["ErrorHandler"] = None

    def __new__(cls) -> "ErrorHandler":
        """Handle new."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        """Handle init."""
        if self._initialized:
            return
        self.logger = _LOGGER
        self.root: Optional[tk.Misc] = None
        self._initialized = True

    def set_root(self, root: Optional[tk.Misc]) -> None:
        """Set (or clear) the Tk root used for message-box operations."""
        self.root = root

    def _show_dialog(self, kind: str, title: str, message: str) -> None:
        """Display a message box on Tk's owning thread when possible."""
        root = self.root
        if root is None:
            return

        def show() -> None:
            """Handle show."""
            try:
                callback = getattr(messagebox, kind)
                callback(title, message, parent=root)
            except (tk.TclError, RuntimeError):
                self.logger.debug("Unable to display %s dialog", kind, exc_info=True)

        if threading.current_thread() is threading.main_thread():
            show()
        else:
            try:
                root.after(0, show)
            except (tk.TclError, RuntimeError):
                self.logger.debug("Unable to schedule %s dialog", kind, exc_info=True)

    def handle_error(
        self,
        error: Exception,
        user_message: str,
        error_title: str = "Error",
        log_exception: bool = True,
        show_dialog: bool = True,
        error_code: str | None = None,
    ) -> None:
        """Log an exception and optionally present a user-friendly error dialog.

        ``error_code`` is a stable support reference. Technical exception text is
        logged, while the dialog remains clear and actionable.
        """
        code = f" [{error_code}]" if error_code else ""
        if log_exception:
            self.logger.error(
                "%s%s: %s", error_title, code, error, exc_info=(type(error), error, error.__traceback__)
            )
        else:
            self.logger.error("%s%s: %s", error_title, code, error)

        if show_dialog:
            display = f"{user_message}\n\nReference: {error_code}" if error_code else user_message
            self._show_dialog("showerror", error_title, display)

        # Preserve the implementation-plan behaviour for domain exceptions.
        if isinstance(error, WayFinderException):
            raise error

    def handle_critical_error(self, error: Exception, user_message: str) -> None:
        """Log a fatal error, notify the user, and request GUI termination."""
        self.logger.critical(
            "Critical error: %s", error, exc_info=(type(error), error, error.__traceback__)
        )
        root = self.root
        if root is None:
            raise error

        self._show_dialog("showerror", "Critical Error", user_message)

        def quit_root() -> None:
            """Handle quit root."""
            try:
                root.quit()
            except (tk.TclError, RuntimeError):
                self.logger.debug("Unable to quit Tk root after critical error", exc_info=True)

        if threading.current_thread() is threading.main_thread():
            quit_root()
        else:
            try:
                root.after(0, quit_root)
            except (tk.TclError, RuntimeError):
                self.logger.debug("Unable to schedule Tk shutdown", exc_info=True)

    def show_warning(self, message: str, title: str = "Warning", error_code: str | None = None) -> None:
        """Log and optionally show a warning message."""
        code = f" [{error_code}]" if error_code else ""
        self.logger.warning("%s%s: %s", title, code, message)
        display = f"{message}\n\nReference: {error_code}" if error_code else message
        self._show_dialog("showwarning", title, display)

    def show_info(self, message: str, title: str = "Information", error_code: str | None = None) -> None:
        """Show an informational message when a Tk root is available."""
        code = f" [{error_code}]" if error_code else ""
        self.logger.info("%s%s: %s", title, code, message)
        display = f"{message}\n\nReference: {error_code}" if error_code else message
        self._show_dialog("showinfo", title, display)
