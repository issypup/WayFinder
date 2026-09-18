"""Provide test ignored persistence support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path

def test_bulk_ignored_runtime_command_exists():
    """Handle test bulk ignored runtime command exists."""
    text=(Path(__file__).parents[2]/"wayfinder"/"runtime"/"server.py").read_text(encoding="utf-8")
    assert 'cmd == "set_ignored"' in text
    assert 'self.ignored_names = {' in text

def test_gui_persists_and_restores_ignored_locations():
    """Handle test gui persists and restores ignored locations."""
    text=combined_app_source()
    assert '"ignored_locations_by_scope"' in text
    assert 'def _persist_ignored_location' in text
    assert 'def _restore_ignored_locations_for_snapshot' in text
    assert 'self.runtime_client.set_ignored_locations(sorted(names))' in text
