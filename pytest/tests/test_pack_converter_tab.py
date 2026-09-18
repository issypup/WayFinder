"""Provide test pack converter tab support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "wayfinder" / "app" / "app.py"

def test_pack_converter_is_dedicated_page_not_map_card():
    """Handle test pack converter is dedicated page not map card."""
    source=combined_app_source()
    assert '"Pack Converter":"⇄  Pack Converter"' in source
    assert 'self._build_pack_converter()' in source
    assert 'def _build_pack_converter(self):' in source
    map_chunk=source[source.index('def _build_map(self):'):source.index('def _build_pack_converter(self):')]
    assert 'Convert PopTracker Pack…' not in map_chunk
    assert 'Convert UT Pack…' not in map_chunk
