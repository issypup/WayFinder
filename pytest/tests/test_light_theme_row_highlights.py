"""Provide test light theme row highlights support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path


def test_dark_theme_recent_and_hint_rows_use_readable_semantic_palette_colours():
    """Handle test dark theme recent and hint rows use readable semantic palette colours."""
    source = combined_app_source()
    assert 'bg="#24151d"' in source
    assert 'sidebar="#3a202d"' in source
    assert 'accent="#ef7896"' in source
    assert 'select="#b84f70"' in source
    assert 'success="#73c9a0"' in source
    assert 'warning="#efb66d"' in source
    assert 'foreground=self._palette()["success"]' in source
    assert 'foreground=self._palette()["warning"]' in source
