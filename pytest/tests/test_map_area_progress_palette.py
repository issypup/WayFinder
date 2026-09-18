"""Regression coverage for the map area progress-bar theme integration."""

from wayfinder.app.app import WayFinderApp


def test_gui_palette_contains_progress_bar_border_color():
    """Handle test gui palette contains progress bar border color."""
    app = WayFinderApp.__new__(WayFinderApp)
    palette = app._palette()
    assert palette["border"]
    assert palette["card"]
    assert palette["accent_soft"]


def test_progress_bar_border_fallback_keys_are_valid():
    """Handle test progress bar border fallback keys are valid."""
    app = WayFinderApp.__new__(WayFinderApp)
    palette = app._palette()
    border = palette.get("border", palette["accent_soft"])
    assert isinstance(border, str) and border.startswith("#")
