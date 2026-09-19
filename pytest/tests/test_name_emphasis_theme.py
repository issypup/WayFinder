"""Provide test name emphasis theme support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path
APP = Path(__file__).resolve().parents[2] / "wayfinder" / "app" / "app.py"
def test_checks_and_map_names_use_hint_emphasis_palette():
    """Handle test checks and map names use hint emphasis palette."""
    source = combined_app_source()
    assert 'style.configure("Emphasis.Treeview"' in source
    assert 'foreground=p["success"]' in source
    assert 'style="Emphasis.Treeview"' in source
    assert 'style="MapName.TCombobox"' in source
    assert 'fill=self._palette()["success"]' in source
    assert 'label_font="WayFinderMarkerLabel"' in source
