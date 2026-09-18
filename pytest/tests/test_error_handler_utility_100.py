"""Provide test error handler utility 100 support."""
import logging

import pytest

from wayfinder.utils.decorators import handle_errors
from wayfinder.utils.error_handler import ErrorHandler


def test_error_handler_is_singleton():
    """Handle test error handler is singleton."""
    assert ErrorHandler() is ErrorHandler()


def test_handle_error_logs_without_gui(caplog):
    """Handle test handle error logs without gui."""
    handler = ErrorHandler()
    handler.set_root(None)
    with caplog.at_level(logging.ERROR, logger="wayfinder"):
        handler.handle_error(ValueError("boom"), "Friendly", show_dialog=False)
    assert "Error: boom" in caplog.text


def test_decorator_preserves_metadata_and_reraises():
    """Handle test decorator preserves metadata and reraises."""
    @handle_errors("Could not do it", show_dialog=False)
    def explode():
        """doc"""
        raise RuntimeError("bad")

    assert explode.__name__ == "explode"
    assert explode.__doc__ == "doc"
    with pytest.raises(RuntimeError, match="bad"):
        explode()
