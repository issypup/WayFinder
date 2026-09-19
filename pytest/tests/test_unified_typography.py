"""Provide test unified typography support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "wayfinder" / "app" / "app.py"

def test_wayfinder_uses_unified_segoe_typography():
    """Handle test wayfinder uses unified segoe typography."""
    source = combined_app_source()
    # Every text role goes through a WayFinder named font built on Segoe UI, so
    # the whole interface tracks the text-size setting live.
    assert 'style.configure("TLabel"' in source
    assert 'font="WayFinderBody"' in source
    assert 'FONT_FAMILY = "Segoe UI"' in source
    assert 'FONT_FAMILY_SEMIBOLD = "Segoe UI Semibold"' in source
    assert 'style.configure("Emphasis.TLabel"' in source
    assert 'font="WayFinderSemibold"' in source
    assert '"Arial"' not in source
    assert '"Tahoma"' not in source
    # Tk's own default fonts are retargeted onto Segoe UI, never used directly.
    assert 'font="TkDefaultFont"' not in source
    assert 'tkfont.nametofont(name, root=root).configure(family=body["family"]' in source

def test_existing_name_emphasis_stays_semibold():
    """Handle test existing name emphasis stays semibold."""
    source = combined_app_source()
    assert 'style.configure("Emphasis.Treeview"' in source
    assert 'style="MapName.TCombobox"' in source
    assert 'label_font="WayFinderMarkerLabel"' in source
    assert '"WayFinderMarkerLabel": dict(family=FONT_FAMILY_SEMIBOLD' in source
